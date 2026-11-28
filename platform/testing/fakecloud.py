import ipaddress
import itertools
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from sandbox import declaration
from sandbox import fabric
from sandbox import openstack
from sandbox.runner import EXIT_MARK

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = "srv-platform"
MANAGEMENT_CIDR = "10.31.0.0/24"
COMPLETE, BUILDING, FAILED = "CREATE_COMPLETE", "CREATE_IN_PROGRESS", "CREATE_FAILED"
DELETING = "DELETE_IN_PROGRESS"


class Cloud:
    def __init__(self):
        self.counter = itertools.count(1)
        self.networks, self.subnets, self.ports, self.groups = [], [], [], []
        self.servers, self.keypairs, self.stacks = [], [], []
        self.images = [{"id": f"img-{role}", "name": f"cr-{role}-bake1", "status": "active"}
                       for role in ("kali", "waf", "infra", "target")]
        self.calls = []
        self.fail_next_stack = ""
        self.steps_to_complete = 1
        self.lock = threading.RLock()
        self.port = 0
        self.fabric()

    def ident(self, kind: str) -> str:
        return f"{kind}-{next(self.counter)}"

    def fabric(self):
        net = {"id": "net-mgmt", "name": fabric.network_name(fabric.MANAGEMENT),
               "tags": [f"{fabric.TAG}={fabric.MANAGEMENT}"], "project_id": "cr"}
        self.networks.append(net)
        self.subnets.append({"id": "sub-mgmt", "network_id": "net-mgmt", "cidr": MANAGEMENT_CIDR,
                             "enable_dhcp": True, "gateway_ip": None, "name": "cr-mgmt", "ip_version": 4})
        self.groups += [{"id": f"g-{name}", "name": name, "security_group_rules": []} for name in fabric.GROUPS]
        self.servers.append({"id": PLATFORM, "name": "cr-platform", "status": "ACTIVE", "metadata": {},
                             openstack.LAUNCHED: "2026-11-18T00:00:00.000000",
                             "addresses": {net["name"]: [{"addr": "10.31.0.2", openstack.FIXED: "fixed",
                                                          "version": 4}]}})
        self.ports.append({"id": "port-platform", "network_id": "net-mgmt", "device_id": PLATFORM,
                           "device_owner": "compute:nova", "name": "cr-platform.mgmt", "tags": [],
                           "fixed_ips": [{"subnet_id": "sub-mgmt", "ip_address": "10.31.0.2"}]})

    def address_on_management(self) -> str:
        taken = {fixed["ip_address"] for port in self.ports for fixed in port.get("fixed_ips") or ()}
        return next(str(host) for host in ipaddress.ip_network(MANAGEMENT_CIDR).hosts() if str(host) not in taken)

    def stack(self, name: str) -> dict | None:
        return next((stack for stack in self.stacks if stack["stack_name"] == name), None)

    def advance(self):
        for stack in list(self.stacks):
            if stack["stack_status"] == BUILDING:
                stack["steps"] -= 1
                if stack["steps"] <= 0:
                    stack["stack_status"] = FAILED if stack.get("fails") else COMPLETE
            elif stack["stack_status"] == DELETING:
                self.remove(stack)

    def remove(self, stack: dict):
        owned = set(stack["owned"])
        for kind in ("servers", "ports", "subnets", "networks", "groups"):
            setattr(self, kind, [one for one in getattr(self, kind) if one["id"] not in owned])
        self.stacks.remove(stack)

    def create_stack(self, body: dict) -> dict:
        stack = {"id": self.ident("stack"), "stack_name": body["stack_name"], "stack_status": BUILDING,
                 "stack_status_reason": "", "tags": body["tags"].split(","), "owned": [],
                 "steps": self.steps_to_complete, "fails": self.fail_next_stack, "template": body["template"],
                 "parameters": body["parameters"]}
        if self.fail_next_stack:
            stack["stack_status_reason"] = self.fail_next_stack
            self.fail_next_stack = ""
        self.apply(stack, body["template"], body["parameters"])
        self.stacks.append(stack)
        return {"stack": {"id": stack["id"]}}

    def apply(self, stack: dict, template: dict, parameters: dict):
        made: dict[str, dict] = {}

        def resolved(value):
            if isinstance(value, dict) and "get_resource" in value:
                return made[value["get_resource"]]["id"]
            if isinstance(value, dict) and "get_param" in value:
                return parameters[value["get_param"]]
            return value

        resources = template["resources"]
        order = sorted(resources, key=lambda name: ["OS::Neutron::Net", "OS::Neutron::Subnet",
                                                    "OS::Neutron::SecurityGroup", "OS::Neutron::Port",
                                                    "OS::Nova::Server"].index(resources[name]["type"]))
        for name in order:
            kind, properties = resources[name]["type"], resources[name]["properties"]
            if kind == "OS::Neutron::Net":
                made[name] = {"id": self.ident("net"), "name": properties["name"], "tags": list(properties["tags"]),
                              "project_id": "cr"}
                self.networks.append(made[name])
            elif kind == "OS::Neutron::Subnet":
                made[name] = {"id": self.ident("sub"), "network_id": resolved(properties["network"]),
                              "cidr": properties["cidr"], "enable_dhcp": properties["enable_dhcp"],
                              "gateway_ip": properties["gateway_ip"], "name": properties["name"], "ip_version": 4}
                self.subnets.append(made[name])
            elif kind == "OS::Neutron::SecurityGroup":
                made[name] = {"id": self.ident("sg"), "name": properties["name"],
                              "security_group_rules": list(properties["rules"])}
                self.groups.append(made[name])
            elif kind == "OS::Neutron::Port":
                network = resolved(properties["network"])
                fixed = [{"subnet_id": resolved(one["subnet"]), "ip_address": one["ip_address"]}
                         for one in properties.get("fixed_ips") or ()]
                if not fixed:
                    fixed = [{"subnet_id": "sub-mgmt", "ip_address": self.address_on_management()}]
                number = next(self.counter)
                made[name] = {"id": f"port-{number}", "network_id": network, "fixed_ips": fixed,
                              "mac_address": f"fa:16:3e:00:{number // 256:02x}:{number % 256:02x}",
                              "tags": list(properties["tags"]), "name": properties["name"],
                              "port_security_enabled": properties.get("port_security_enabled", True),
                              "security_groups": [resolved(one) for one in properties.get("security_groups") or ()],
                              "allowed_address_pairs": properties.get("allowed_address_pairs") or [],
                              "device_id": "", "device_owner": ""}
                self.ports.append(made[name])
            else:
                server = {"id": self.ident("srv"), "name": properties["name"], "status": "ACTIVE",
                          "metadata": dict(properties["metadata"]), "image": resolved(properties["image"]),
                          "flavor": resolved(properties["flavor"]), "user_data": properties["user_data"],
                          openstack.LAUNCHED: "2026-11-18T01:00:00.000000", "addresses": {}}
                for entry in properties["networks"]:
                    port = next(one for one in self.ports if one["id"] == resolved(entry["port"]))
                    port.update(device_id=server["id"], device_owner="compute:nova")
                    net = next(one for one in self.networks if one["id"] == port["network_id"])
                    server["addresses"].setdefault(net["name"], []).extend(
                        {"addr": fixed["ip_address"], openstack.FIXED: "fixed", "version": 4}
                        for fixed in port["fixed_ips"])
                made[name] = server
                self.servers.append(server)
        stack["owned"] = [resource["id"] for resource in made.values()]

    def listed(self, items: list[dict], query: dict) -> list[dict]:
        found = items
        if "tags" in query:
            wanted = set(query["tags"][0].split(","))
            found = [one for one in found if wanted <= set(one.get("tags") or ())]
        if "tags-any" in query:
            wanted = set(query["tags-any"][0].split(","))
            found = [one for one in found if wanted & set(one.get("tags") or ())]
        if "network_id" in query:
            found = [one for one in found if one.get("network_id") == query["network_id"][0]]
        return found

    def get(self, path: str, query: dict):
        if path.startswith("/stacks"):
            self.advance()
            return 200, {"stacks": [{key: value for key, value in stack.items() if key not in ("owned", "template")}
                                    for stack in self.listed(self.stacks, query)]}
        for key, items in (("/v2.0/networks", self.networks), ("/v2.0/subnets", self.subnets),
                           ("/v2.0/ports", self.ports), ("/v2.0/security-groups", self.groups)):
            if path.startswith(key):
                return 200, {key.rsplit("/", 1)[1].replace("-", "_"): self.listed(items, query)}
        if path.startswith("/servers/detail"):
            return 200, {"servers": self.servers}
        if path.startswith("/os-keypairs"):
            return 200, {"keypairs": [{"keypair": one} for one in self.keypairs]}
        if path.startswith("/v2/images"):
            return 200, {"images": self.images}
        return 404, {"error": path}

    def post(self, path: str, body: dict):
        if path == "/stacks":
            return 201, self.create_stack(body)
        if path == "/v2.0/networks":
            made = {"id": self.ident("net"), "tags": [], **body["network"]}
            self.networks.append(made)
            return 201, {"network": made}
        if path == "/v2.0/subnets":
            made = [{"id": self.ident("sub"), **one} for one in body["subnets"]]
            self.subnets += made
            return 201, {"subnets": made}
        if path == "/v2.0/security-groups":
            made = {"id": self.ident("sg"), "security_group_rules": [], **body["security_group"]}
            self.groups.append(made)
            return 201, {"security_group": made}
        if path == "/v2.0/security-group-rules":
            rule = {"id": self.ident("rule"), **body["security_group_rule"]}
            next(one for one in self.groups if one["id"] == rule["security_group_id"])["security_group_rules"].append(rule)
            return 201, {"security_group_rule": rule}
        if path == "/v2.0/ports":
            made = {"id": self.ident("port"), "device_id": "", "device_owner": "", "fixed_ips": [], "tags": [],
                    **body["port"]}
            self.ports.append(made)
            return 201, {"port": made}
        if path == "/os-keypairs":
            self.keypairs.append(body["keypair"])
            return 201, {"keypair": body["keypair"]}
        if re.fullmatch(r"/servers/[^/]+/os-interface", path):
            return 200, {"interfaceAttachment": body["interfaceAttachment"]}
        return 404, {"error": path}

    def delete(self, path: str):
        found = re.fullmatch(r"/stacks/([^/]+)/([^/]+)", path)
        if found:
            stack = next((one for one in self.stacks if one["id"] == found[2]), None)
            if stack is None:
                return 404, {"error": path}
            stack["stack_status"] = DELETING
            return 204, None
        ident = path.rsplit("/", 1)[1]
        for kind in ("servers", "ports", "subnets", "networks", "groups", "images"):
            setattr(self, kind, [one for one in getattr(self, kind) if one["id"] != ident])
        self.keypairs = [one for one in self.keypairs if one["name"] != ident]
        return 204, None

    def put(self, path: str, body: dict):
        found = re.fullmatch(r"/v2.0/networks/([^/]+)/tags", path)
        if found:
            next(one for one in self.networks if one["id"] == found[1])["tags"] = list(body["tags"])
            return 200, body
        return 404, {"error": path}

    def handler(self):
        cloud = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self, code, body, headers=None):
                raw = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length)) if length else None

            def _route(self, verb):
                split = urlsplit(self.path)
                path, query = unquote(split.path), parse_qs(split.query)
                body = self._body() if verb in ("POST", "PUT") else None
                with cloud.lock:
                    cloud.calls.append((verb, path, query, body))
                    if verb == "POST" and path == "/v3/auth/tokens":
                        here = f"http://127.0.0.1:{cloud.port}"
                        return self._answer(201, {"token": {"catalog": [
                            {"type": service, "endpoints": [{"interface": "public", "region_id": "RegionOne",
                                                             "url": here}]}
                            for service in ("network", "compute", "image", "orchestration")]}},
                            {"X-Subject-Token": "tok"})
                    code, answer = getattr(cloud, verb.lower())(path, *([query] if verb == "GET" else
                                                                         [] if verb == "DELETE" else [body]))
                self._answer(code, answer)

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PUT(self):
                self._route("PUT")

            def do_DELETE(self):
                self._route("DELETE")

        return Handler

    def nodes_of(self, slot: int) -> dict[str, dict]:
        return {server["metadata"]["cr_node"]: server for server in self.servers
                if server["metadata"].get("cr_slot") == str(slot)}

    def control_address(self, slot: int, node: str) -> str:
        server = self.nodes_of(slot)[node]
        return server["addresses"][fabric.network_name(fabric.MANAGEMENT)][0]["addr"]


def serving(cloud: Cloud):
    server = ThreadingHTTPServer(("127.0.0.1", 0), cloud.handler())
    cloud.port = server.server_port
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    return server


def adapter(cloud: Cloud, slots: int = 2, **build) -> openstack.OpenStack:
    here = f"http://127.0.0.1:{cloud.port}"
    spec = openstack.Cloud(keystone=here, neutron=here, nova=here, glance=here, heat=here, project="cr",
                           user="cr", ssh_user="ubuntu", ssh_key="/nonexistent")
    built = openstack.Build(source=str(ROOT), flavor="dba.small", inside={"mgmt": MANAGEMENT_CIDR},
                            platform=PLATFORM, slots=slots, **build)
    return openstack.OpenStack(declaration.read(), spec, openstack.http_reader(spec, "secret"), build=built)


class Runner:
    def __init__(self):
        self.ran: list[tuple[str, str]] = []
        self.answers: list[tuple[str, str, int]] = []
        self.lock = threading.Lock()

    def answer(self, matching: str, output: str, exit_code: int = 0):
        self.answers.insert(0, (matching, output, exit_code))

    def __call__(self, host, command, stdin, timeout):
        sent = command[-1]
        address = next(word.split("@", 1)[1] for word in command if "@" in word and not word.startswith("-"))
        with self.lock:
            self.ran.append((address, sent))
            output, code = next(((said, code) for matching, said, code in self.answers if matching in sent), ("", 0))
        return subprocess.CompletedProcess(command, 0, output, f"{EXIT_MARK}{code}\n")

    def sent_to(self, address: str) -> list[str]:
        return [sent for reached, sent in self.ran if reached == address]
