# OpenStack

This file says what this project needs from an OpenStack cloud and how to set
one up from nothing. It covers the cloud (Kolla-Ansible 2025.1 or later), the project,
the one base image, `cloud.yaml`, the platform VM, the range and the checks. It
is written for an operator who rebuilds the cloud side or onboards a new cloud.
`README.md` has the numbered steps to bring the product up. This file has the
detail behind them. §9 builds the whole cloud in one VM so you can check that it
works.

Words used in this file:

- **Range**: what the platform builds for training: one Heat stack per
  lease on OpenStack, from a pool of stacks built ahead.
- **Lease**: one ready range stack given to an operator (`POST /api/leases/`)
  for one or more rounds or a lesson, or to the probe recorder; see the
  glossary in `docs/ARCHITECTURE.md`.
- **Range stack**: the Heat stack `cr-slot-<n>` one lease uses: four VMs,
  `kali`, `waf`, `infra` and `target`, on five Neutron networks of the stack's
  own (`internet`, `dmz`, `web-outer`, `web-inner`, `mgmt`), with no router.
  A lease is given a ready stack when it opens; when it closes or expires, the
  stack is deleted and created again. The number `<n>` (N) is the stack
  number; see the glossary in `docs/ARCHITECTURE.md`. The code calls it the
  slot (`Lease.slot`, `/api/staff/range/pool/`).
- **Pool**: the stacks that stand ready ahead of leases, so many per
  wargame (`compute.pool`). A close replaces the used stack off the
  learner's path.
- **Role image**: a Glance image a range VM boots from, baked once from
  `deploy/roles/<role>/` (`cr-<role>-bake1` by default).
- **Range VM**: one of a range stack's four VMs.
- **Infra**: the range VM no learner gets a shell on: the edge router between
  `internet` and `dmz` (nftables), the inline IDS (Suricata on a Linux bridge
  between `web-outer` and `web-inner`) and the log server.
- **Fabric**: the management network `cr-mgmt`, the security groups and the
  keypair the platform creates before the stacks (`POST /api/staff/range/fabric/`).
  Every range VM has one control port on `cr-mgmt`.
- **Store**: the platform's SQLite database (`db.sqlite3`).
- **Substrate**: what the platform builds the range on (`CR_SUBSTRATE`); here
  `range.openstack.connect`.

Facts marked **(this cloud)** come from the cloud the product has run on since
2026-10-20: Kolla-Ansible on three nodes, `con01` (10.0.0.11), `com01`
(10.0.0.31) and `stg01` (10.0.0.41). We read them from that cloud on 2026-10-20.
The operator reaches 10.0.0.0/24 and the provider network through a VPN. From
2026-10-11 to 2026-10-20 the product ran on an earlier cloud (an all-in-one host
`master`, ML2/OVS). Where this file quotes a measurement from that time, it says
"the previous cloud". Everything else comes from this repo's code or from the
sources listed at the end.

Runs and measurements dated before 2026-11-19 ran the tree before the side
split (`platform/api/`); the routes and modules they quote
(`/api/sessions/`, `/api/range/slot/`, `ready/`, `configure/`,
`api/reset.py`, `range/sandbox.py`) are that tree's and are kept as the
record. The procedures name the side split's routes, the staff range API
under `/api/staff/range/` (`GET /`, `fabric/`, `leftovers/`, `pool/`), which
has not yet run on a cloud.

## Target: one-click build

The end state is one command that builds the whole environment. Nothing is
compiled or installed by hand on the cloud's hosts. The cloud holds the stock
Ubuntu 24.04 cloud image, which `bin/cloud init` uploads, a Kali base image,
and the four role images baked from `deploy/roles/` (§3.6).

On the controller node, after `kolla-ansible post-deploy`:

```bash
git clone https://github.com/Nekonic/fsl-project-mvp.git && cd fsl-project-mvp
uv run bin/cloud init
uv run bin/cloud up
```

The repo is a uv project: `pyproject.toml` at the root declares the
platform's dependencies, the groups `dev` (pytest, pytest-django), `cloud` (openstacksdk,
python-openstackclient, python-heatclient, what `bin/cloud` needs), and
`uv.lock` pins them all. "When `uv run` is
used, the project is locked and synced before invoking the requested command"
[U3], so `uv run bin/cloud` makes or updates `.venv` at the repo root first
and no separate `uv sync` is needed; `[tool.uv] default-groups` is `dev` and
`cloud`. Everything else installs from the same lock with
`uv sync --frozen` ("use the lockfile without checking if it is up-to-date"
[U3]): `bin/verify`, the platform VM's `cr-venv` (§5.1) and the sideload
hand-over, and the platform image, which syncs into the image's
system Python (`UV_PROJECT_ENVIRONMENT=/usr/local`, `--inexact` so the
image's own pip stays) from the lock bind-mounted into the build. That image
therefore builds from the repo root (`.github/workflows/images.yml`,
`compose.yaml`), and its matrix entry lists `sources`, the paths a sideload
compares (`platform`, `pyproject.toml`, `uv.lock`).

`bin/cloud init` runs with admin credentials and prepares what a member user
cannot (§3): the project and its user, the clouds.yaml entry that holds the
user's password, flavor access, the base image and `cloud.yaml` (§4).

1. `bin/cloud up` reads `deploy/openstack/cloud.yaml` (§4). It has Heat create
   the platform VM (`deploy/openstack/platform.yaml`). On first boot the VM pulls
   the control-plane images from GHCR. It does not build them. The range VMs
   boot from the role images in Glance (§3.6).
2. The script gives the VM the password and the range ssh key over ssh.
3. The script then drives the platform's staff range API in this order:
   `POST fabric/`; `DELETE leftovers/`, which removes what the ranges before
   this one left (§5.5); `POST pool/`, which owes every slot no lease holds a
   refill that the `rebuild` service carries out (create the stack if it is
   missing, stale or failed, wait for its nodes, seed its sensor with the
   baseline rules). Then it waits until `GET /api/staff/range/` shows every
   slot's refill `idle`, and stops on one that `failed`.

| Piece | Status | Where |
|---|---|---|
| Kolla-Ansible cloud with Heat, Glance, Nova, Neutron (ML2/OVN) | done (this cloud) | §2 |
| Project `fsl-range`, member user, clouds.yaml entry, quota check, flavor choice | `bin/cloud init` as admin (2026-11-15); flavors and quotas are never created or raised by it | §3 |
| Base image, stock Ubuntu 24.04, upload with checksum check | `bin/cloud init` when missing; done (this cloud, 2026-10-20) | §3.6 |
| Role images `cr-<role>-bake1` | baked by hand from `deploy/roles/<role>/install.sh`; active in Glance (this cloud, 2026-11-18; the WAF's re-baked as `cr-waf-bake2`). The side split's infra and WAF changes need a new bake of both, not done (§3.7) | §3.6 |
| `cloud.yaml`: every cloud-specific value, validated | written by `bin/cloud init` (2026-11-15) | §4 |
| Platform and wargame images on GHCR (`.github/workflows/images.yml`) | done (public, pulled 2026-10-11) | §5 |
| Heat stack pulls images instead of `--build` | done (2026-10-11) | §5 |
| `bin/platform-rebuild`: replace the VM without losing data (store and range key carried over), driven by `cloud.yaml` | done (2026-10-15, `bin/cloud up --replace --sideload` twice, 28 and 55 min with a 6 GB store) | §5 |
| `bin/cloud up`, `bin/cloud down` | done (2026-10-11); since 2026-10-20 `up` after `down` restores the newest backup that holds rows (run live 2026-10-20) | §5 |
| Fabric via `POST /api/staff/range/fabric/` | done on the old tree (`POST /api/range/fabric/`); the side split's route has not run on a cloud | §6 |
| Range stacks `cr-slot-<n>`, a pool per wargame, replaced at close | live since 2026-11-18 on the old tree (`POST /api/range/slot/`): the first pool fill created the four stacks (§6.1), and two full `bin/verify` runs ran on them. The side split's `POST /api/staff/range/pool/` and the `rebuild` service's refill have not run on a cloud | §6 |
| Acceptance on the OpenStack substrate | runs on the Heat range; the latest full run and its open failures are in `docs/state/now.md` | §7 |

Steps below are tagged **[one-click]** where `bin/cloud up` does them for you,
**[init]** where `bin/cloud init` does them with admin credentials, and
**[admin, once]** where an admin does them by hand.

## 1. What this project needs from OpenStack

The platform builds the range as one Heat stack per lease, `cr-slot-<n>`,
each four Nova servers on Neutron networks of the stack's own (§6). It creates them
as a member user. cloud-init writes `CR_SUBSTRATE=range.openstack.connect` on
the platform VM to select this. The range's design was
`docs/superpowers/specs/2026-11-18-heat-range-design.md` (archived; git keeps
it); the side split keeps it and adds the edge sets, the WAF access log, the
scratch CRS instance and `analyst` (§3.7,
`docs/superpowers/specs/2026-11-19-side-split-design.md`).

The platform VM runs only the control plane as containers: platform,
Elasticsearch, Kibana and the collector. `docker compose` pulls their
prebuilt images from GHCR. Every acceptance test runs and passes on OpenStack
(`docs/DECISIONS.md` 2026-10-11, which replaced the 2026-10-08 spec's
"OpenStack work, not MVP"); the one skip is by design (§7).

The cloud therefore holds the platform VM `cr-platform` and four VMs per
stack of the pool: with the default pool `{board: 3, corp: 1}`, 16 range VMs.

The platform calls these APIs (`platform/range/openstack.py`, the only file
that knows them):

- Keystone v3, with password authentication in the configured domain.
- Heat: create, list (by tag) and delete the range stacks.
- Nova: servers, keypairs and `os-interface`.
- Neutron: networks with tags, subnets, ports and security groups.
- Glance v2: list and delete the project's own images that the VM range of
  before left (§5.5).

The operator also uses Heat for the platform VM. The project uses no Cinder,
Octavia or Designate.

## 2. What the cloud needs (Kolla-Ansible 2025.1 or later)

The product supports OpenStack deployed with Kolla-Ansible 2025.1 or later (the
user's ruling of 2026-10-24: later releases are much the same). **(this cloud)**
It runs the Kolla images tagged 2025.2 (seen on 2026-10-24:
`quay.io/openstack.kolla/cinder-backup:2025.2-ubuntu-noble` on `stg01`), so the
commands below use 2025.2. Any release from 2025.1 on is installed the same way:
change `2025.2` to that release in the `pip install` line, the constraints URL
and `openstack_release`. The previous cloud ran 2026.1, and the measurements
marked as coming from it are about 2026.1.

**(this cloud)** kolla-ansible (Nova reports microversion 2.100), Ubuntu images, ML2/OVN
with Geneve tenant networks, and `nova_compute_virt_type: "kvm"`. The nodes are:

- `con01` (10.0.0.11) is the controller. The API address
  (`kolla_internal_vip_address`) is 10.0.0.10, and every public endpoint is
  `http://10.0.0.10:<port>`.
- `com01` (10.0.0.31) is the one compute node. Its root logical volume was
  extended so that Nova reports `local_gb` 546.
- `stg01` (10.0.0.41) is the storage node, with the Cinder LVM backend `lvm-1`.
  The product does not use Cinder. We mention the node because its cinder-volume
  was down from 2026-09-18 to 2026-10-20. Kolla's default volume group is
  `cinder-volumes`, which does not exist on `stg01`, so the rendered config named
  a missing group. The fix was `cinder_volume_group: "ubuntu-vg"` in
  `globals.yml`.

The sections below show the all-in-one steps, because §9 builds that. A
multi-node cloud such as this one uses the same `globals.yml` keys with its own
inventory.

**ML2/OVN and DNS.** With ML2/OVN, Neutron tells each VM's DHCP client which DNS
resolvers to use. If `[ovn] dns_servers` is empty, Neutron uses the resolvers of
the `neutron-server` host's own `/etc/resolv.conf`. Under systemd-resolved, that
is `127.0.0.53`, which means nothing to a VM (`get_dhcp_dns_servers` in
`neutron/common/ovn/utils.py`). A subnet created with the DNS server `0.0.0.0`
announces no resolver at all [N3]. The platform creates the `cr-mgmt` subnet
that way (`platform/range/openstack.py`), because the management network needs
no resolver, and a range stack's own subnets have DHCP off. The product therefore does not depend on `[ovn] dns_servers`. A
cloud admin who wants the cloud's other VMs to resolve names sets
`[ovn] dns_servers` in `neutron.conf` (Kolla: an override file, §2.3's
mechanism). §8 has the symptom.

**MTU.** The tenant networks' MTU is 1442 on OVN (Geneve) and 1450 on VXLAN with
ML2/OVS. Neutron hands it to every VM, the platform VM sets Docker's MTU to its
network's (§5.1), and the target bake sets Docker's to the builder's
(`deploy/roles/target/install.sh`, `CR_MTU` overrides it).

### 2.1 Install and deploy [admin, once]

These commands follow the 2025.2 quickstart [K1]:

```bash
sudo apt install -y git python3-dev libffi-dev gcc libssl-dev libdbus-glib-1-dev python3-venv
python3 -m venv /opt/kolla-venv && export PATH=/opt/kolla-venv/bin:$PATH
pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2025.2
pip install docker dbus-python
sudo mkdir -p /etc/kolla && sudo chown $USER:$USER /etc/kolla
cp -r /opt/kolla-venv/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
cp /opt/kolla-venv/share/kolla-ansible/ansible/inventory/all-in-one .
kolla-ansible install-deps
kolla-genpwd
# edit /etc/kolla/globals.yml (below)
kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one --use-test-images
kolla-ansible deploy -i ./all-in-one
pip install python-openstackclient python-heatclient -c https://releases.openstack.org/constraints/upper/2025.2
kolla-ansible post-deploy -i ./all-in-one        # writes /etc/kolla/clouds.yaml
```

Three details in these lines each fixed a failure in the 2026-10-20 trial (§9):

- `pip install docker dbus-python` puts both modules in the Kolla venv.
  `bootstrap-servers` installs `python3-docker` for the system Python, but an
  all-in-one run uses the venv's Python, and `prechecks` stops at "Checking
  docker SDK version" without the module. `dbus-python` needs
  `libdbus-glib-1-dev`.
- `--use-test-images` is needed because the images come from the
  `quay.io/openstack.kolla` namespace, which `prechecks` calls test-only.
  `deploy` takes no such flag.
- `post-deploy` needs `-i ./all-in-one`. Without it, it looks for
  `/etc/kolla/ansible/inventory/all-in-one` and stops.

The kolla venv has no Heat client. `bin/cloud` does not need it: `uv run`
installs its own clients (Target, above). `post-deploy` also writes
`/etc/kolla/clouds.yaml`, whose `kolla-admin` entry `bin/cloud init` signs in
with [K10].

### 2.2 globals.yml

```yaml
kolla_base_distro: "ubuntu"                   # the example file defaults to rocky; match the host [K1]
openstack_release: "2025.2"
network_interface: "<NIC with the management IP>"
neutron_external_interface: "<NIC up with no IP: floating IPs and the external network>"
kolla_internal_vip_address: "10.0.0.10"       # this cloud's API address: an unused address on network_interface's network [K1]
nova_compute_virt_type: "kvm"                 # the default [K7]; recommended. Without VT-x or AMD-V, "qemu" runs everything, only slower
neutron_plugin_agent: "openvswitch"           # the default [K2]; this cloud runs ML2/OVN, and the product runs on either
enable_heat: "yes"        # default follows enable_openstack_core [K2]; keep it on
enable_horizon: "yes"     # optional; the platform does not use it
#enable_cinder: false     # default [K2]; the project works without volumes
#cinder_volume_group: "ubuntu-vg"   # only if Cinder is on and the host's volume group is not Kolla's default, cinder-volumes (this cloud)
```

Heat, Glance, Nova, Neutron, Keystone and Placement are all part of
`enable_openstack_core`, which is true by default [K2]. Nothing else is
required.

KVM is recommended, not required (the user's ruling of 2026-11-15). Kolla's
default `nova_compute_virt_type` is `kvm` [K7], which needs VT-x or AMD-V on the
compute hosts. A host without them can set `nova_compute_virt_type: "qemu"`:
Nova then runs the platform VM and the range VMs under plain QEMU emulation.
Everything still runs, only slower. The hosts are Ubuntu 24.04 on x86_64, because every image the project
runs is amd64.

On an all-in-one cloud without HAProxy and keepalived, set `enable_haproxy:
"no"`. Set `kolla_internal_vip_address` to the IP of `network_interface` itself
[K2]. The API endpoints are then that address. Keystone is on port 5000. This is
the `auth_url` of the project user's clouds.yaml entry (`http://ADDRESS:5000`,
§4).

Set `enable_proxysql: "no"` beside it. ProxySQL is enabled with MariaDB, not
with HAProxy, and it binds port 3306 on the VIP. Here the VIP is the host's own
address, so MariaDB then cannot bind its port and `deploy` fails with "Address
already in use".

### 2.3 Tap-as-a-Service (optional; dropped from the design)

We enabled TaaS on the previous cloud (ML2/OVS) on 2026-09-30 for a sensor owned
by the organiser. We then dropped that sensor (`docs/STATE.md`, "Tap-as-a-Service
is dropped from the design"). Nothing uses TaaS, and a new cloud does not need
it. The steps below are the ones we ran on the previous cloud, and they assume
the Open vSwitch agent. To enable it on 2026.1, the release of the previous cloud:

```yaml
enable_neutron_taas: "yes"     # defined in ansible/group_vars/all/neutron.yml, default false [K3]
```

```bash
cp /etc/kolla/globals.yml /etc/kolla/globals.yml.before-taas
kolla-ansible reconfigure -i /root/all-in-one -t neutron
```

**The 2026.1 bug.** Measured on the previous cloud. We did not run TaaS on 2025.x. The
same code is in `stable/2025.2` (read, not run): the task copies
`neutron_taas.conf` only for `neutron-server` and `neutron-openvswitch-agent`,
and `neutron.conf.j2` lists the service plugins for every Neutron service. So
the bug probably applies there too; this is not checked on 2025.x.


- kolla-ansible adds `taas` to `service_plugins` for all three Neutron API
  services.
- Its config task writes `neutron_taas.conf` only for the services in
  `services_need_neutron_taas_conf`, which are `neutron-server` and
  `neutron-openvswitch-agent` [K4].
- `neutron_rpc_server` and `neutron_periodic_worker` then exit with `No
  providers specified for 'TAAS'`, and every agent reads dead.

The fix uses kolla's per-service override. The same task merges the file
`{{ node_custom_config }}/neutron/{{ item.key }}.conf` [K4][K5]:

```bash
c=/etc/kolla/neutron-server/neutron_taas.conf
mkdir -p /etc/kolla/config/neutron
cp $c /etc/kolla/config/neutron/neutron-rpc-server.conf
cp $c /etc/kolla/config/neutron/neutron-periodic-worker.conf
kolla-ansible reconfigure -i /root/all-in-one -t neutron
openstack network agent list          # every agent Alive :-)
docker ps --filter name=neutron       # rpc_server and periodic_worker Up
```

A later reconfigure kept the override files on the previous cloud. We checked as
a member: a tap service plus a `BOTH` tap flow goes ACTIVE and `br-tap` exists. We
did not check whether upstream fixed this after 2026.1.

### 2.4 Nova: resize is off

`allow_resize_to_same_host` is `False` by default [N1]. An all-in-one cloud has
no other host, so a resize cannot be scheduled. This cloud has one compute node
(`com01`) and does not change the setting. To change a server's flavor you must
**replace** the server.

Heat's `OS::Nova::Server` applies a flavor change as a resize unless
`flavor_update_policy: REPLACE` is set [H1]. Replace the stack (delete and
create, as `bin/platform-rebuild` does). Do not update the flavor.

To allow resize instead, set `[DEFAULT] allow_resize_to_same_host = True` in
`/etc/kolla/config/nova.conf`. Then run `kolla-ansible reconfigure -t nova`
[K5][N1].

### 2.5 External network and floating IPs [admin, once]

The platform VM is reached on a floating IP. The platform VM and the role
image builders download their packages and images through a router on an
external network. A fresh
Kolla-Ansible cloud has none.

Kolla maps `neutron_external_interface` to the physical network `physnet1` on
`br-ex` [K8]. Run these as admin, in a shell that has loaded
`/etc/kolla/admin-openrc.sh`, which `kolla-ansible post-deploy` writes (§3). Use
the subnet, gateway and pool of the
network that interface is wired to:

```bash
openstack network create --external --provider-network-type flat --provider-physical-network physnet1 provider
openstack subnet create --network provider --no-dhcp --subnet-range 10.10.10.0/24 \
  --gateway 10.10.10.1 --allocation-pool start=10.10.10.20,end=10.10.10.99 provider-subnet
```

**(this cloud)** The `provider` network is flat. Its subnet is 192.168.2.0/24
with gateway 192.168.2.1 and the pool 192.168.2.200 to 192.168.2.250.

`provider` is `network.external` in `cloud.yaml`. The gateway must be a real
router that reaches the Internet. The pool must hold only addresses that nothing
else on that network uses. Each floating IP and the gateway address of each
tenant router come from the pool.

### 2.6 Internet egress

The router gives the project's networks source NAT to the Internet. DNS is
`network.dns`. The hosts below must be reachable through it. If you filter with
an allowlist, also allow the hosts the registries redirect to.

The platform VM's first boot and the Ubuntu role bakes install from the
Kakao mirror (`http://mirror.kakao.com/ubuntu/`, every pocket, `noble-security`
included) instead of the archive. They try `apt-get update` and their install
up to ten times, 15 s apart, and the install's exit decides each try: a failed
`apt-get update` is not retried by itself. On 2026-11-17 two of the
archive's servers (91.189.91.94 and .95, behind
`nova.clouds.archive.ubuntu.com`) answered 404 for `dists/noble/Release` for
more than half an hour while the others answered 200; `apt-get update` keeps
the address it resolved, so a single try failed the platform VM's boot three
times in a row, and a second `apt-get update` on the same VM succeeded. The
same day the Kakao mirror's `noble-security` `InRelease` was hours older than
its `main/dep11/Components-amd64.yml.xz` (46,388 bytes against 46,360 in the
`InRelease`, "Mirror sync in progress?"): `apt-get update` exited 100 on every
try although every `Packages` index downloaded, and the install those indexes
allow ran only once the install stopped waiting on the update's exit.

| Who | Reaches | For |
|---|---|---|
| platform VM (cloud-init, `cr-platform.service`, `cr-venv`) | mirror.kakao.com; github.com; ghcr.io; docker.elastic.co; geoip.elastic.co; pypi.org and files.pythonhosted.org | `apt` (Docker, git, nodejs, chrony); `git clone` of `platform.repository` and the uv release tarball; `cr-platform`; Elasticsearch, Kibana and Filebeat; `bin/fetch-geoip`; `uv sync` into `/opt/cr/.venv` |
| a builder baking a role image (`deploy/roles/<role>/install.sh`, §3.6) | mirror.kakao.com (Ubuntu roles), Kali's apt mirror (kali); github.com and nginx.org (waf); Docker Hub (infra, target); ghcr.io (target) | the role's packages; ModSecurity, its connector, nginx's source and CRS; `jasonish/suricata` and MySQL; `cr-board`, `cr-corp`, `cr-corp-db` |
| the controller node, where `bin/cloud` runs | the cloud's API; the floating IP; github.com; ghcr.io; pypi.org and files.pythonhosted.org | `bin/cloud`; `git ls-remote`; the check that the images can be pulled; `uv run`'s sync |

A range stack has no way to the Internet: none of its LANs has a Neutron
router, and each range VM's control port on `cr-mgmt` (no gateway, DNS
`0.0.0.0`) is in the group `cr-mgmt`, whose egress reaches only the platform
and DHCP (§3.5). Everything a range VM runs is in its baked image; only the
role bakes need egress. `test/test_range_isolation.py` checks that no learner shell
reaches the Internet or the metadata address (§8).

## 3. Project, user, quotas, flavors, keys, groups, images

Everything runs on the controller node. `bin/cloud init` does §3.1, §3.2's
check, §3.3's choice, §3.4's key file and §3.6's upload. It signs in as admin
with the `kolla-admin` entry of `/etc/kolla/clouds.yaml`, which
`kolla-ansible post-deploy` writes [K10]; when the shell has `OS_AUTH_URL` set
(after `source /etc/kolla/admin-openrc.sh` [K1][K9]), it uses those `OS_*`
variables instead. It leaves what exists in place, so it can run again at any
time. The commands below are what it does, for a cloud where an admin does it
by hand. `bin/cloud up` and `bin/platform-rebuild` then sign in as the project
user from that user's clouds.yaml entry (§4).

### 3.1 Project and user [init]

```bash
openstack project create fsl-range
openstack user create --project fsl-range --password-prompt fsl-range
openstack role add --project fsl-range --user fsl-range member
```

`init` makes the project and the user when they are missing, gives the user
`member` on the project, and writes the user's credentials into
`~/.config/openstack/clouds.yaml` as the entry `cloud.yaml` names (`cloud:
fsl-range`), mode 0600, merged into the file without touching its other
entries. The password is random (`secrets.token_urlsafe`) and never printed or
logged. An entry that already signs in is kept. A user that exists while no
working entry holds its password stops `init`; `--reset-password` gives the user
a new one, which a standing platform VM learns only through
`bin/cloud up --replace`. The domains are the entry's `user_domain_name` and
`project_domain_name` when an entry exists, `Default` otherwise.

**(this cloud)** The project and the user sit in the domain `fsl` (id
`c72af53edecb4e31a5645fdd9a07f0f9`), so the commands above also take `--domain
fsl`, and the clouds.yaml entry sets `user_domain_name` and
`project_domain_name` to `fsl`. The project `fsl-range`
has the id `3c82e428f6cc4997949a89f5fdee68c7`. The user `fsl-range` is a member
of it. The platform signs in as this member user, never as admin.

### 3.2 Quotas [admin, once; init checks]

`init` reads the project's limits (`instances`, `cores`, `ram`,
`floating_ips`) and stops, naming each one short, unless they hold the
platform VM and the pool: 1 + 4 × stacks instances, the platform flavor's vCPU
and RAM plus, per stack, the four role flavors' (`compute.flavors.<role>`), and
1 floating IP; stacks is the sum of `compute.pool` (`quota_shortfall` in
`platform/range/cloud.py`). It compares limits, not usage, and never raises a
quota. It does not read `security_groups`: the range takes the same number of
groups for any pool size (below). A shortfall names the remedy: an admin raises the quota, or
`compute.pool` asks for fewer stacks.

- The platform VM is 2 vCPU, 8 GB RAM and 60 GB disk (`m1.large`).
- Each range stack is four VMs, `kali`, `waf`, `infra` and `target`, on their
  role flavors (`dba.small` unless `cloud.yaml` names another, §3.3).
- Each stack also has five networks, six subnets (the `internet` LAN holds
  two) and 14 ports of its own (§6). Its LAN ports use the three groups
  `cr-lan-<digest>` that every stack shares (§3.5).

Nova has no per-project disk quota. The flavor disk of every VM is space that
the compute node's instance storage must have, at a disk allocation ratio of
1.0 [N2].

**(this cloud)** These are the figures:

- The project quota is 24 cores, 57344 MB of RAM and 17 instances (recorded
  2026-11-13). It was Nova's default, 20 / 51200 / 10, until 2026-10-24.
- The default pool `{board: 3, corp: 1}` is four stacks of four VMs; with the
  platform VM that is 17 instances, the whole instance quota
  (`docs/DECISIONS.md`, 2026-11-18). The four stacks of `dba.small` VMs stand
  on com01 (2026-11-18); how much memory headroom that leaves, and whether
  `dba.small` is enough for the target's Docker and MySQL under load, are
  **[unverified]**.
- The fabric holds 1 network (`cr-mgmt`) with 1 subnet, and the groups
  `cr-reach`, `cr-mgmt`, `cr-egress` and `cr-senders`. The platform's stack
  also needs 1 network, 1 router and 1 floating IP.
- The quota is 10 security groups and 100 security group rules (`openstack
  quota show`, 2026-11-18). `default`, `cr-platform` and the fabric's four
  groups hold 6; the three `cr-lan-` groups make 9, for any pool size. With
  five groups per range stack, as before, every stack of the pool of four
  failed with `OverQuotaClient: Quota exceeded for resources:
  ['security_group']` (`docs/DECISIONS.md`, 2026-11-18).

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 17 fsl-range   # example
```

### 3.3 Flavors [admin, once; init chooses]

A member user cannot create flavors, and `init` never creates one: the user
ruled that flavors are not created for them. `init` lists every flavor as
admin, public and private. For the platform it picks the smallest that fits,
by RAM, then vCPU, then disk; a flavor `cloud.yaml` already names is kept when
it fits. For each range VM role it takes the flavor `compute.flavors.<role>`
names, `dba.small` when none, and stops, naming the flavors there are, when
the cloud has no flavor of that name. It prints each choice, makes a private
flavor visible to the project (`openstack flavor set --project`), and stops,
printing the `openstack flavor create` an admin would run, when no platform
flavor fits.

| Role | vCPU | RAM | Disk |
|---|---|---|---|
| `platform` | 2 or more | 8 GB or more | 40 GB or more |

`compute.flavors` in `cloud.yaml`:

| Key | Use | Notes |
|---|---|---|
| `platform` | platform VM | 8 GB RAM or more. With 4 GB, the OOM killer once killed Elasticsearch when sessions stacked up (DECISIONS 2026-10-10). Example `m1.large` (8 GB / 2 vCPU / 60 GB) |
| `kali`, `waf`, `infra`, `target` | each range VM of that role | optional; `dba.small` when left out, the WAF included (`docs/DECISIONS.md`, 2026-11-18). Every role image has `min_disk` 30 GB, which `dba.small`'s 30 GB holds; an image baked on a larger disk does not fit it (§3.6). The target runs the wargame's front and MySQL under Docker, with the memory limits of `deploy/roles/target/wargames.yaml` |

**(this cloud)** The cloud has `m1.large` (8 GB / 2 vCPU / 60 GB), `m1.medium`
(4 GB / 2 vCPU / 30 GB), `dba.small`, `dba.medium` (8 GB / 4 vCPU / 40 GB) and
`dba.range` (16 GB / 6 vCPU / 60 GB). `cloud.yaml` names `m1.large` for
`platform`; the range VM roles take `dba.small`. A range VM keeps its flavor
until its stack is replaced, and a new flavor name makes every stack stale (§6).
Check that every flavor `cloud.yaml` names exists on your cloud.

```bash
openstack flavor create --ram 8192 --vcpus 2 --disk 60 m1.large
```

A new cloud that has no fitting platform flavor makes this one, and a flavor
for the range VM roles if it has no `dba.small`; name it in `compute.flavors`.

### 3.4 Keypairs

- `fsl-claude` is the Nova keypair the platform VM boots with: the server's
  `key_name`, which is `keys.key_name` in `cloud.yaml` and the stack parameter
  `key_name`. Its private key is `keys.key_file`, the key `bin/cloud` and
  `bin/platform-rebuild` ssh to the VM with. `init` makes the key when the
  file is missing (`ssh-keygen -t ed25519 -N "" -f ~/.ssh/fsl_claude`); nothing
  else is done by hand. Before they create the stack, both scripts look the keypair up
  (`openstack keypair list`) and, when the project has none of that name,
  import `<key_file>.pub` with `openstack keypair create --public-key` [O1]
  (`ensure_keypair` in `bin/platform-rebuild`). A keypair of that name that
  holds another public key (`openstack keypair show --public-key`) stops them
  with the keypair's name and is never overwritten: whatever booted with it
  would lose its key. A missing `.pub` stops them too;
  `ssh-keygen -y -f <key_file>` writes it from the private key.
- `cr-platform` is the platform's own range key. `POST /api/staff/range/fabric/`
  imports it from `/data/ssh/id_ed25519` in the platform container. Every range
  VM boots with it (`key_name`), and each node's user data gives its public key
  to the management user (§6). Never create this keypair by hand. The key file it comes from (`keys.range`) needs no step
  either. The first `bin/cloud up` on a cloud with no stack makes the file if it
  is missing. §6.3 covers a mismatch between the two.

### 3.5 Security groups

| Group | Made by | Rules |
|---|---|---|
| `cr-platform` | Heat stack | tcp 22, tcp 2222 (the Kali jump), tcp 8000, tcp 8002, icmp in |
| `cr-reach` | fabric | on the platform's `cr-mgmt` port; nothing in except udp 123 (NTP) from members of `cr-mgmt` and udp 5140 (the collector) from members of `cr-senders` |
| `cr-mgmt` | fabric | on every range VM's control port; all IPv4 in, only from members of `cr-reach` (the platform's `cr-mgmt` port); out only to members of `cr-reach` and to udp 67 (DHCP) |
| `cr-senders` | fabric | also on each stack's infra control port, the only sender the collector takes; no rule in; out only to members of `cr-reach` and to udp 67 |
| `cr-egress` | fabric | no rule in; the fabric creates it and no port uses it |
| `cr-lan-<digest>` | the platform, before it creates a range stack | one per distinct LAN rule set, shared by every stack; `<digest>` is the first 12 hex of the rules' SHA-256. Three for board and corp alike: all IPv4 in (`internet`, `dmz`), all in from 10.30.128.0/24 (`web-outer`, `web-inner`), tcp 514 from 172.29.0.0/24 (`mgmt`) (§6) |

Neutron gives a new group an allow-all egress rule for IPv4 and IPv6. For
`cr-mgmt` and `cr-senders` (`networks.CONFINED_GROUPS`) `POST fabric/` deletes
every egress rule but the two above and adds whichever of the two is
missing, on groups it creates and on groups already standing, so the next
`bin/cloud up` fixes a cloud whose groups were made before. DHCP on
`cr-mgmt` hands each VM a route to 169.254.169.254 through 10.31.0.1, the OVN
metadata port; with the egress confined, that traffic is dropped and no
range VM reaches the metadata service. The range VMs boot from a config
drive and do not need it (`docs/DECISIONS.md`, 2026-11-18). The second full
`bin/verify` on the Heat range found Kali, the WAF and board reaching
169.254.169.254 before this rule; that the rule closes it live is
**[unverified]** until the next `bin/cloud up` and verify run.

`bin/cloud up` deletes the groups `cr-range` and `cr-build` of the ranges
before (§5.5). `DELETE fabric/` deletes the `cr-lan-` groups after the
range stacks (§6.2).

Port 8002 is the console's site pane (`/site/<round>/<host>/`, proxied to
`match/site.py`). The platform sends each request over an ssh stream to the
lease's Kali VM (over `cr-mgmt`). For an attack seat it goes through
`attack.send` from the current origin; for a
defence or lesson seat the infra VM sends it from a customer address with the
lease's browse marker, out of its DMZ port straight to the WAF. A platform stack
made before 2026-10-13 lacks the rule. Add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 8002 cr-platform
```

Port 2222 is the jump for a seat's own ssh to its box: an sshd that
`platform/entrypoint.sh` starts inside the platform container, beside ttyd,
from `range/jump.py`'s config (`python -m range.jump`). It takes only the
user `jump`, by public key, with no shell, no TTY and only local forwarding;
each key's line is
`restrict,port-forwarding,permitopen="<the box's control address>:22"`.
`GET /api/rounds/<round>/attack/terminal/` issues the attack seat a key for
Kali's `kali` user, and `GET /api/rounds/<round>/defence/terminal/` the
defence seat a key for the WAF's `analyst` (§3.7), who may write only the defence's WAF files; each answer
carries the private key once, with the jump's host and port, and puts the
public key into the box account's and the jump's `authorized_keys`. The
round's end revokes both. Each box's control port takes tcp 22 only from the
platform's group, so no floating IP is needed per box. A platform stack made
before the jump lacks the 2222 rule; a stack update adds it.

The range has no Internet, so the platform is its only time source.

- The platform VM runs chrony. cloud-init sets `allow <network.mgmt>` and `local
  stratum 10`, so the platform keeps serving its own clock if it loses its
  upstream time source.
- Every range VM takes its time from the platform's `cr-mgmt` address through
  a `systemd-timesyncd` drop-in (`/etc/systemd/timesyncd.conf.d/60-cr.conf`,
  `NTP=<platform mgmt>`) in its user data. A rebuilt platform VM keeps that
  address: the fabric attaches the detached `cr-platform.mgmt` port to it
  (§5.3).
- A platform VM booted before 2026-10-15 lacks chrony. Run what cloud-init runs:

```bash
sudo install -d /etc/chrony/conf.d
printf 'allow 10.31.0.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/cr-range.conf
sudo apt-get -y install chrony
```

Port 3080 served the GNS3 map until 2026-11-15. The learner map is now
`GET /api/rounds/<round>/topology/` on port 8000, and the Heat template no
longer opens 3080; a stack update removes the rule from a stack made before.

### 3.6 Images

Glance holds three kinds of image:

| Image | How it gets there | One-click |
|---|---|---|
| `compute.base_image` (e.g. `ubuntu-24.04`) | the stock `noble-server-cloudimg-amd64.img`, checksum verified, uploaded as is (below) | `bin/cloud init`, once |
| the Kali base | Kali's Generic Cloud image (`kali-linux-<ver>-cloud-genericcloud-amd64.tar.xz`), converted and uploaded once **[unverified]** | by hand, once |
| `cr-kali-bake1`, `cr-waf-bake1`, `cr-infra-bake1`, `cr-target-bake1` (**(this cloud)** the WAF's is `cr-waf-bake2`) | baked from `deploy/roles/<role>/install.sh` on a builder VM, then a Nova snapshot (below) | by hand, once per bake |

The platform VM installs or writes every package, tool, key and setting at
boot from the base image. The range VMs boot from the baked images with no
egress; only `/etc/slot.env`, the management user and the time source come in
their user data (§6).

`init` looks the base image up by `compute.base_image`. When there is none it
downloads `noble-server-cloudimg-amd64.img` from
`https://cloud-images.ubuntu.com/noble/current/`, compares its SHA-256 with
that directory's `SHA256SUMS` and uploads it as qcow2, public. An image that
the project cannot see (neither public nor the project's) is made public. Two
images of that name stop it, and so does one that is not `active` (an upload
cut short leaves it `queued`); delete it and run `init` again. By hand, as
admin:

- `SHA256SUMS` lists one line per file of that build. `--ignore-missing` checks
  only the file you downloaded [U1].
- Without `--public`, an admin's image belongs to the admin project and
  `fsl-range` does not see it. The stack then fails on its `image`.
- As `fsl-range` (`--os-cloud fsl-range`, §4), the same command without
  `--public` works, because the image then belongs to the project.

```bash
curl -fLO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
curl -fLO https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
openstack image create --public --disk-format qcow2 --container-format bare \
  --file noble-server-cloudimg-amd64.img ubuntu-24.04
```

The `.img` file is a qcow2 disk. `SHA256SUMS.gpg` beside it signs the list. To
check the signature as well, import Ubuntu's cloud-image signing key and compare
its fingerprint with the one Ubuntu publishes. Then run `gpg --verify
SHA256SUMS.gpg SHA256SUMS`.

**(this cloud)** The admin uploaded `ubuntu-24.04` and made it public.

**The role images.** Each `deploy/roles/<role>/install.sh` runs as root on a
builder VM that has egress, is idempotent, and ends by clearing cloud-init and
the machine id (`cloud-init clean --logs`, an empty `/etc/machine-id`), so
every range VM booted from the snapshot is a new instance. The role's boot
units wait for `/etc/slot.env` (`ConditionPathExists`), so they do nothing on
the builder. Several files in a role directory are links into the repo
(`deploy/kali/`, `deploy/proxy/stamp.py`, `deploy/waf/`, `deploy/suricata/`,
each wargame's `compose.yaml`); copy the directory with the links resolved.

| Role | Builder's base | `install.sh` installs |
|---|---|---|
| `kali` | the Kali base | `kali-linux-headless` and the tools of the Kali container before (nmap, sqlmap, nikto, whatweb, ffuf, gobuster, hydra, dirb, mitmproxy and others), the stamp proxy as `web-proxy.service`, the operator log hook, `set-origin`, `slot-boot`, and a key-only `kali` user with bash and passwordless sudo; `board.com` and `corp.com` resolve to 121.134.88.42; sslh's systemd generator masked and `cloud-init.target` wanted by `multi-user.target`, so cloud-init runs on every boot (`docs/TROUBLESHOOTING.md` "A Kali VM booted without cloud-init") |
| `waf` | `compute.base_image` | nginx 1.24 from Ubuntu, ModSecurity 3.0.16 and its nginx connector built from release tarballs checked by SHA-256, CRS 4.25.1, the repo's `modsecurity.conf` and `board.com.conf` (the JSON access log of every request), rsyslog, nftables, python3, the scratch CRS test's `probe.conf` and `probe-upstream.py` in `/usr/local/share/cr/` with its scratch folder `/var/lib/cr-crstest`, the `analyst` account (`analyst.sh`), `slot-boot` |
| `infra` | `compute.base_image` | nftables, conntrack, tcpdump, bridge-utils, ethtool, rsyslog, Docker with `bridge: none` and no iptables, the pinned `jasonish/suricata` image (`suricata -T` run on the repo's config and rules), the `suricatasc` wrapper (`docker exec -i sensor suricatasc`), `edge.nft` with the `pool` and `spent` sets, the offline rule test's scratch folder `/var/lib/cr-ruletest`, `sensor.service`, `slot-boot`; `suricata` itself is only in the `sensor` container |
| `target` | `compute.base_image` | Docker and Compose; board's and corp's compose files rendered for a VM (`render.py`: fronts published on the stack's addresses, databases on the internal `<w>_backend`), their images pulled from GHCR at `CR_IMAGE_TAG` (required), brought up once and their volumes kept as the pristine data, `wargames.service` |

The Ubuntu roles point apt at the Kakao mirror, purge `snapd` and
`modemmanager`, and retry `apt-get` up to ten times (§2.6).

The builder's flavor sets the image's disk. A Nova snapshot takes the
builder's root disk as the image's virtual size and `min_disk`, and Heat
refuses a range stack whose flavor has less disk than its image's `min_disk`
(`StackValidationFailed: Image cr-waf-bake1 requires 40 GB minimum disk
space. Flavor dba.small has only 30 GB.`). Bake on a flavor whose disk is no
larger than the range VMs' flavor's, 30 GB for `dba.small`. **(this cloud)**
`m1.medium` (2 vCPU, 4 GB, 30 GB) fits and has more vCPU for the source builds
than `dba.small`.

A bake by hand, for one role, goes like this; the builder needs a network with
a router (the platform stack's `cr-platform`) and a way in for ssh, here the
group `cr-platform` and a floating IP. As a procedure it is **[unverified]**:

```bash
openstack server create --image ubuntu-24.04 --flavor m1.medium --network cr-platform \
  --security-group cr-platform --key-name fsl-claude --wait cr-bake-waf2
openstack floating ip create provider; openstack server add floating ip cr-bake-waf2 <address>
scp -r deploy/roles/waf ubuntu@<address>:/tmp/waf          # scp -r follows the links
ssh ubuntu@<address> 'sudo sh /tmp/waf/install.sh'          # the target: sudo env CR_IMAGE_TAG=<compute.target_tag> sh ...
openstack server stop cr-bake-waf2
openstack server image create --wait --name cr-waf-bake2 cr-bake-waf2
openstack server delete cr-bake-waf2; openstack floating ip delete <address>
```

The builder needs no floating IP when ssh reaches it through the platform VM,
which has a port on `cr-platform`: the WAF re-bake of 2026-11-18 went that
way.

The builder takes one instance of the project's quota, and the full default
pool takes all of it (§3.2: 17 of 17 on this cloud), so `server create`
fails while the pool stands. Free one first: an admin raises `instances` by
one, or one range stack is deleted for the bake.

A builder named `cr-build-<...>` or carrying the `cr_image` property would be
deleted by `DELETE leftovers/` and `bin/cloud down` as a builder of the VM
range; name it otherwise.

**(this cloud)** The four images `bake1` were baked by hand on 2026-11-18
(`docs/DECISIONS.md`). `cr-waf-bake1` was baked on a builder with a 40 GB disk,
so its `min_disk` is 40 GB and `dba.small` cannot boot it; it was baked again,
unchanged from `deploy/roles/waf/`, as `cr-waf-bake2` on an `m1.medium`
builder: `install.sh` took 12 min 53 s (ModSecurity built from source), the
snapshot 2 min 30 s. `cloud.yaml` names `compute.images.waf: cr-waf-bake2`;
`cr-waf-bake1` stays in Glance, unused. The range stacks boot `cr-kali-bake1`,
`cr-waf-bake2`, `cr-infra-bake1` and `cr-target-bake1`, each of virtual size
30 GB and `min_disk` 30 GB, which `dba.small`'s 30 GB holds (§3.3). How long
the other bakes take and how long the Kali image takes to boot once it is
cached on the compute node are **[unverified]**. `cr-kali-bake2` was baked on
2026-11-18 from `deploy/roles/kali/` on `dev` (sslh's generator masked,
`cloud-init.target` wanted) on an `m1.medium` builder from `cr-kali-base`,
reached through the platform VM as the user `kali`: the builder's
`cloud-init-local` took about 5 min before ssh answered, `install.sh` 43 min
27 s, the snapshot 10 min 54 s; virtual size 30 GB, `min_disk` 30 GB.

A range stack names its images by `compute.images`, and the stack's digest
holds the names, not the content (§6, §7): bake a changed role under a new
name. The target holds the board and corp images it pulled at bake, so a
changed wargame image reaches the range only through a new target bake. That
bake's `CR_IMAGE_TAG` is the full commit `compute.target_tag` names (§4); a
new target bake is a new image name and a new `target_tag`, both in the
digest, so every stack is replaced. The target's boot refuses to report ready
when an `image:` line in `/opt/wargames/*/compose.yaml` carries another tag,
and writes those lines into `/var/lib/cr/failed` (§6). A line pinned by digest
(`mysql@sha256:...`) has no tag and passes.

### 3.7 The side split's rebake (infra and WAF)

The side split changes two role images; kali and target are unchanged. Until
both are baked and named in `compute.images`, a range runs the old edge and
WAF: the WAF's error log is not shipped, so no origin is ever spent, a spent
origin is not dropped at the edge, and the rule test has no scratch CRS instance or `analyst` account to
reach. The procedure is the bake by hand of §3.6, once per role, under new
names; none of it has run, so it is **[unverified]**.

| Role | New name | What changed in `deploy/roles/<role>/` |
|---|---|---|
| `infra` | `cr-infra-bake2` | `edge.nft` declares the sets `pool` and `spent` (`type ipv4_addr`) and drops `ip saddr @spent` and then `ip saddr != @pool` from `wan` before the established accept, so an open keep-alive or sqlmap connection of a spent origin stops too and an address the platform never put in `pool` reaches nothing; `range/edge.py` adds the addresses after each `slot-boot` load and flushes a spent origin's conntrack entries (package `conntrack`). `tcpdump` for `rules.suricata.capture` (probe recording), `/var/lib/cr-ruletest` (0700) for `rules.suricata.offline_test`, which runs the same pinned image and `/etc/suricata/suricata.yaml` with `-r` and reads the scratch `eve.json`, never `/var/log/suricata`. `log-relay.conf` relays the WAF's `nginx-access` lines instead of `nginx` |
| `waf` | `cr-waf-bake3` (**(this cloud)**; `cr-waf-bake2` is taken) | `board.com.conf` writes every request to `/var/log/nginx/access.json` as JSON (`time`, `client_ip`, `vhost`, `request`, `status`, `refused` from the one `$refused` map of 400 and 403, `request_id` from `X-Request-ID` when it has a marker's shape and empty otherwise, so a padded or repeated header cannot push the line past the shipper's 64 KiB), and `log-shipper.conf` ships it under Tag `nginx-access` in place of `refused.log`. `probe.conf` and `probe-upstream.py` for `rules.crs.scratch_check` and `scratch_test`; the exclusion file is created 0644 (root writes it through sudo). `analyst.sh` creates the defence seat's account |

`pool` holds a round's attack origins (filled when
the round starts) or, for a probe lease, the origin it wears (admitted before
each case); every other address from `wan` is dropped, so a learner with sudo
on kali cannot send from an unused origin-subnet address. On a fresh slot the
set is empty and kali reaches nothing on the target. Each round start empties
both sets before it fills them
(`range.edge.restart`), so a lease's next round does not inherit the last
round's spent origins. The round's end empties both sets again, so
between rounds nothing from kali reaches the target, a process the learner
left running there included.

**The `analyst` account** (`deploy/roles/waf/analyst.sh`), which the defence
seat's terminal and its jump grant log in as (when the round ends and the
grant is revoked, `range.jump.end_account` clears its crontab and `at` jobs,
disables its linger, ends its logind sessions and kills its processes):

- can: log in by the per-seat key `range/jump.py` writes into its
  `authorized_keys` (bash, password field `*`); read `/etc/nginx` (the vhosts,
  `modsecurity.conf`, the CRS tree and the exclusion file) and, through group
  `adm`, `/var/log/nginx` and `/var/log/modsecurity`; run `sudo nginx -t` and
  `sudo nginx -T` and nothing else as root;
- cannot: write any file under `/etc/nginx`, `/var/log/nginx` or
  `/var/log/modsecurity` (no group it is in may write there; the bake removes
  any such group write bit), reload or signal nginx, read
  `/var/lib/cr-crstest` (0700), forward ports or sockets over its ssh login
  (`/etc/ssh/sshd_config.d/60-analyst.conf`), or send anything on the network
  from the WAF: `/etc/nftables.conf`, loaded by `nftables.service`, drops
  every packet a process of `analyst` sends (`meta skuid analyst drop`).

The defence posture itself changes only through the defence API.

**After the bakes**, name `compute.images.infra: cr-infra-bake2` and
`compute.images.waf: cr-waf-bake3` in `cloud.yaml` and run `bin/cloud up
--replace` (§7): every stack no lease holds is stale and is rebuilt. Then,
on one slot, the spec's checks for this step:

```bash
sudo nft list set ip edge spent                    # on the infra: the set exists, empty until an origin is spent
sudo nft list set ip edge pool                     # on the infra during a round: its attack origins
sudo tail -1 /var/log/nginx/access.json            # on the WAF after one request: request_id is the X-Request-ID
```

- a request's access line reaches Elasticsearch as module `nginx_access` with
  its `request_id`, and a 200 makes no Detection (`GET defence/alerts/`);
- a WAF rule test (`POST defence/waf/test/`) returns a verdict for one case,
  and the live audit log's line count is unchanged;
- an IDS rule test (`POST defence/ids/rules/test/`) leaves
  `/var/log/suricata/eve.json` unchanged;
- as `analyst`, `touch /etc/nginx/x`, `sudo nginx -s reload` and `curl
  http://127.0.0.1/` all fail, and `sudo nginx -T` prints the configuration;
- as `analyst`, `nohup sleep 9999 &` and a crontab line are gone once the
  round ends (`pgrep -u analyst` and `sudo crontab -l -u analyst` on the WAF
  show nothing);
- on kali, `sudo ip addr add <an unused origin-subnet address> dev <its
  internet NIC>` and `curl --interface <that address> http://board.com/`
  time out, while the API's requests still answer;
- a closed round's `/vm-terminal/<side>/<round>/ws` answers `409` with code
  `round_closed`, not 500;
- after a round ends, `sudo nft list set ip edge pool` on the infra is empty
  and a `curl http://board.com/` left running on kali times out;
- on kali, `curl -H "X-Request-ID: $(printf 'a%.0s' $(seq 200))"
  http://board.com/` leaves an access line whose `request_id` is empty and
  whose `client_ip` is the worn origin.

**Probe recordings** follow the bake (spec step 12): `bin/record-probes board`
and `bin/record-probes corp` (`--platform http://<platform>:8000`, a staff
sign-in from `CR_ADMIN_USER` and `CR_ADMIN_PASSWORD`) start a probe lease
through `POST /api/staff/wargames/<id>/probes/record/` and follow
`GET /api/staff/probes/<lease>/` until it is released; a case it could not
record fails the run and is named. The platform writes the recordings to its
`CR_PROBES_OUT` (`/data/probes` in `compose.yaml`, on the `platformdata`
volume); no route serves them, so copy them off the platform VM and commit
them:

```bash
ssh ubuntu@<platform> "sudo docker exec cr-platform tar -C /data/probes/board/probes -cf - ." \
  | tar -C wargames/board/probes -xf -
```

### 3.8 Benign traffic moves to the infra (infra and kali rebake)

The customers program (`deploy/traffic/users.py`) and the benign cases no
longer run on kali. Until the infra is rebaked, a range has no customers:
the platform starts `cr-customers.service` on the infra and the old image
has no such unit, so starting the customers fails and the round records the
error in `Round.traffic`.

| Role | What changed in `deploy/roles/<role>/` |
|---|---|
| `infra` | `install.sh` creates the system account `cr-users` and `/var/lib/cr-users`, installs `users.py` (a link to `deploy/traffic/users.py`) into `/usr/local/lib/cr-users/` and the unit `cr-customers.service` (not enabled; the platform starts it with a round's plan and stops it at the round's end), and installs `python3` and `curl`. `slot-boot` puts the slot's customer addresses (`CUSTOMERS` in `/etc/slot.env`) on a dummy link `customers` as /32s and points the sites (`SITES`) at the WAF's front in `/etc/hosts` |
| `kali` | nothing in its role files; it stands on one address per origin now, which comes from `/etc/slot.env`, not the image. It is rebaked with the infra so both images come from the same tree |

The customers leave the infra's DMZ port, which already allows every source
address (the pair `0.0.0.0/0`, since it routes), and reach the WAF's front
directly; the WAF answers through its default route, the infra. No Heat
change: no network path is new. The customer addresses are not in the
edge's `pool`, so kali cannot send from them.

After the bakes, name both in `compute.images` and run `bin/cloud up
--replace`. Checks on one slot, **[unverified]**:

```bash
ip -4 addr show dev customers                      # on the infra: the slot's customer addresses as /32s
getent hosts board.com                             # on the infra: the WAF's front
sudo systemctl status cr-customers.service         # on the infra during a round: active
sudo tail -1 /var/log/nginx/access.json            # on the WAF: a customer's client_ip and request_id
```

### 3.9 A random board secret per round (target rebake)

A round's start runs `python manage.py set_passwords` in the board
container (the `rotate` command of `wargames/board/objectives.yaml`'s
secret) before it reads the baseline. The command reads a JSON map of
username to password on stdin: the customers' accounts (`accounts` in
`wargames/board/traffic.yaml`) get the password the platform generated for
the round and put in the customers' plan; every other account, `admin`
among them, gets a random one nobody is told. The command is in the
`cr-board` image, which the target image pulls at its bake, so until
`cr-target` is baked again at a commit whose `cr-board` has it, every round
start fails with `ground_truth_unavailable`. After the bake, name it in
`compute.images` (and `compute.target_tag`) and run `bin/cloud up --replace`.
Check on one slot, **[unverified]**: two rounds in a row read different
hashes for every account, and the customers' log-ins still answer 302.

## 4. cloud.yaml

`deploy/openstack/cloud.example.yaml` is committed. `bin/cloud init` writes
`deploy/openstack/cloud.yaml` (git ignores that file) from it, and on later runs
changes only the keys it owns, `cloud`, `network.external`,
`compute.base_image` and `compute.flavors.platform`, and writes `network.allowed`
(its value, or `[0.0.0.0/0]` when it has none), line by line, keeping every other
value and every comment. No secret goes in it, only the name of the clouds.yaml
entry that holds the password. `platform/range/cloud_config.py` reads the
file. It refuses the file before touching anything and names every problem by
its dotted key. The problems it finds include an unknown key, a missing key,
overlapping CIDRs and an `identity` section or a password written into the file.

The identity is not in `cloud.yaml`. It is the entry of the standard
OpenStack client configuration, `~/.config/openstack/clouds.yaml`, that the
key `cloud` names (`fsl-range`); `init` writes it (§3.1). `bin/cloud` and
`bin/platform-rebuild` read `auth.auth_url`, `auth.username`, `auth.password`,
`auth.project_name`, `auth.user_domain_name`, `auth.project_domain_name`,
`region_name` and `interface` (`public` when absent) from it
(`cloud_config.signed_in`), and stop before any change when the entry is missing,
saying to run `bin/cloud init`, or when one of them is, naming it. They need no
RC file and no `OS_*` variables: they drop every `OS_*` variable from their own
environment and run the openstack CLI with `OS_CLOUD=<entry>` and
`OS_CLIENT_CONFIG_FILE=<that file>`, so a sourced RC cannot override the entry.
`auth_url` is Keystone's base URL, `http://10.10.10.10:5000` in the example
(**(this cloud)** `http://10.0.0.10:5000`); a trailing `/v3` is dropped.
`user_domain_name` is the user's domain, by name (**(this cloud)** `fsl`); the
platform signs in with it. `interface` is the catalogue interface the CLI and
the platform call; the platform VM needs one it reaches, `public` here. The
password reaches the platform VM over ssh stdin, into
`/opt/cr/openstack-password` (mode 0600, owned by uid 10001, the platform
container's `cr`). Compose mounts that file read-only into the platform as the
secret `openstack_password` (`/run/secrets/openstack_password`), and the
platform reads it at start (§5.3). It is never on a command line, in a log or
in a container's environment.

| Key | Example | Used by |
|---|---|---|
| `cloud` | `fsl-range` | the clouds.yaml entry to sign in with |
| `network.external` | `provider` | the stack's router and floating IP |
| `network.address` | `""` (**(this cloud)** `192.168.2.247`) | optional; a floating IP the project already holds. The stack associates it and never releases it, so the address survives `bin/cloud down` and every rebuild. If empty, the stack allocates a new one (§5.1) |
| `network.dns` | `[8.8.8.8, 8.8.4.4]` | the platform network's DNS |
| `network.allowed` | `[0.0.0.0/0]` | optional; the source networks the group `cr-platform` takes ssh, the Kali jump 2222, 8000 and 8002 from, one rule per network and port. `init` writes the default. Keep the network `bin/cloud` runs from in it, or the rebuild cannot reach the VM over ssh. Without it, open to all |
| `network.platform`, `.mgmt` | `10.20.0.0/24`, `10.31.0.0/24` | The platform VM's network and the fabric's `cr-mgmt`, where every range VM has its control port. The ranges must be private and must not overlap. They must also stay outside Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`'s networks and the declared origins. A range stack's own LANs take their addresses from `wargames/<w>/topology.yaml`, the same in every stack (§6) |
| `compute.base_image` | `ubuntu-24.04` | the platform VM, and the builder of the Ubuntu role images (§3.6) |
| `compute.availability_zone` | `""` | the platform VM and every range VM; if empty, Nova chooses |
| `compute.flavors` | `platform`, and `kali`, `waf`, `infra`, `target` | §3.3. A range VM role left out takes `dba.small`; `CR_OPENSTACK_FLAVORS` |
| `compute.images` | `cr-<role>-bake1` per role (**(this cloud)** `waf: cr-waf-bake2`) | optional; each range VM role's Glance image, baked from `deploy/roles/<role>/` (§3.6); a role left out takes `cr-<role>-bake1`; `CR_OPENSTACK_IMAGES` |
| `compute.pool` | `{board: 3, corp: 1}` | optional; how many range stacks stand ready for each wargame, each one Heat stack of four VMs, so how many leases can be open at once (§6.4); `CR_OPENSTACK_POOL` |
| `compute.target_tag` | the commit the target image was baked at | optional; the full 40-hex commit whose board and corp images the target image pulled (its bake's `CR_IMAGE_TAG`, §3.6); a range stack has no egress, so it runs only those. Without it, the commit `cr-target-bake1` was baked at; `CR_OPENSTACK_TARGET_TAG` |
| `keys.key_name`, `keys.key_file` | `fsl-claude`, `~/.ssh/fsl_claude` | the Nova keypair the platform VM boots with (its `key_name`, §3.4), and that keypair's private key, for ssh to the VM |
| `keys.range` | `~/.ssh/fsl-platform` | the platform's range key, kept across rebuilds; every range VM takes it for the management user (§6) |
| `platform.stack`, `.repository`, `.ref` | `cr-platform`, this repo, `dev` | the stack, and the checkout it clones |
| `backups.keep` | `1` | optional; how many store backups `backups/` keeps after a rebuild or `down`, counting the new one (`bin/backup --keep`). Without it, one |

`network.estate`, `network.mtu`, `compute.slots` and `compute.flavors.range`,
which the range host used, are read and ignored, so a `cloud.yaml` written for
it still parses (§5.5).

Where each value goes:

- `bin/platform-rebuild` and `bin/cloud` run the openstack CLI with the
  clouds.yaml entry (`OS_CLOUD`, `OS_CLIENT_CONFIG_FILE`).
- They pass every Heat parameter from the file and the entry's identity
  (`Cloud.heat_parameters()`: `keystone`, `user`, `domain`, `region`,
  `interface` come from the entry).
- The template has no defaults. It writes the values into
  `/opt/cr/openstack.env` as `CR_OPENSTACK_*`.
- The platform reads those variables (`settings.py`). If one it needs is
  missing, it refuses and names the variable.

## 5. The platform VM

### 5.1 The Heat stack

`deploy/openstack/platform.yaml` creates:

- the network `cr-platform` (`network.platform`)
- a router to `network.external`
- the group `cr-platform`
- a port
- a floating IP
- a server from `compute.base_image`

The server's cloud-init does these steps:

1. Installs Docker, git, nodejs and chrony from the Kakao mirror, up to ten
   tries (§2.6).
2. Sets Docker's MTU to the network's MTU.
3. Adds 4 GB of swap.
4. Clones `repository` at `ref` into `/opt/cr`.
5. Writes `/opt/cr/openstack.env`. It holds every cloud value except the
   password, among them `CR_OPENSTACK_POOL`, `CR_OPENSTACK_TARGET_TAG`,
   `CR_OPENSTACK_IMAGES` and `CR_OPENSTACK_FLAVORS` (§4) and `CR_OPENSTACK_SSH_USER=ubuntu`, the range
   VMs' management user, and `CR_TOOL_IMAGE=cr-kali`, the attacker host the
   launcher runs tools on. It makes `/opt/cr/openstack-password` empty, mode 0600, owned by
   uid 10001; the hand-over fills it.
6. Writes `/opt/cr/.env` with `CR_PUBLISH=<fixed IP>`,
   `CR_SYSLOG_PUBLISH=0.0.0.0` and `CR_IMAGE_TAG` (the clone's commit), and
   fetches the GeoIP database (`bin/fetch-geoip`).
7. Enables `cr-platform.service`, which runs `docker compose pull` and
   `up -d`.
8. Installs uv from its GitHub release tarball, pinned to one version and
   checked against that tarball's SHA-256, into `/usr/local/bin/uv` [U2].
9. Makes `/opt/cr/.venv` in the background (the unit `cr-venv`):
   `uv sync --frozen --project /opt/cr --python /usr/bin/python3`, from the
   checkout's `uv.lock`.

When `network.address` is set, `bin/platform-rebuild` does this before it
deletes anything:

1. It looks the floating IP up by address (`openstack floating ip list
   --floating-ip-address`).
2. It refuses to go on if the project holds no such floating IP.
3. It passes the floating IP's id as `floating_ip_id`.

The stack then creates an `OS::Neutron::FloatingIPAssociation` instead of an
`OS::Neutron::FloatingIP`. Deleting the association only sets the floating IP's
`port_id` to null (Heat `neutron/floatingip.py`,
`FloatingIPAssociation.handle_delete`). The address stays in the project.

Neutron's default policy lets only an admin choose the address, so the floating
IP is created once, as admin. **(this cloud)** `openstack floating ip create
--project fsl-range --floating-ip-address 192.168.2.247 provider`.

`CR_PUBLISH` is the VM's fixed IP. Port 8000 therefore listens on that address,
not on loopback, and the floating IP NATs to it. Setting `CR_PUBLISH=0.0.0.0` on
a VM is an environment error (DECISIONS 2026-10-10).

The password stays out of Heat and out of user data. Nova's metadata service
answers inside the containers on the VM, so anything in user data can be read
there.

### 5.2 One command [one-click]

Run this on the controller node after `bin/cloud init` (§3). `uv run`
installs the clients (Target, above); the scripts find the `openstack` command
beside the Python they run under.

```bash
uv run bin/cloud up            # --replace to replace a standing platform; --cloud, --ref, --sideload as in §5.3
uv run bin/cloud down
```

Every line `bin/cloud` prints, its own and `bin/platform-rebuild`'s, starts
with the local time (`HH:MM:SS`), so a run's log shows how long each step took.
It asks the platform's API every 5 s while it waits (`POLL`), and
`bin/platform-rebuild` tries ssh and `/api/auth/csrf/` every 2 s (`SSH_POLL`,
`API_POLL`).

`up` does these steps in order:

1. It refuses to run without a usable `cloud.yaml`.
2. It reads the stack's status. It refuses while the status is `*_IN_PROGRESS`.
3. If the stack is absent, it creates it. If the stack is `*_FAILED`, it deletes
   the stack (`--wait`) and creates it again.
   (`--replace` replaces a working stack through `bin/platform-rebuild`, below.)
4. It asks the VM over ssh whether it took its hand-over, whether or not the API
   answers, and then waits for the API. A container can answer before the
   password line is written, and a range build on it would fail. The hand-over
   is the step that gives a new VM the password, the range key and the store
   (§5.3). A VM never took it when `/opt/cr/openstack-password` is missing or
   empty. In that case `up` does the hand-over first. If the
   `cr-platform` container is stopped, `up` starts it first, because the key is
   written into that container. The redone hand-over keeps every other line of
   `openstack.env`, `CR_SIDELOADED` included. `up` refuses a `--sideload` here,
   because it applies only to a new VM.
5. It sends `POST fabric/`. It stops on drift (a resource that exists but
   differs from what the platform would create).
6. It sends `DELETE leftovers/`, which removes what the ranges before this one
   left in the project (§5.5), servers first, since a leftover server holds
   quota the range VMs need, and prints what it removed.
7. It sends `POST pool/`, which owes every slot no lease holds a refill
   (`range/refill.py`) and answers each slot's refill state. The `rebuild`
   service (`manage.py rebuild_slots`) carries the refills out in its loop: for a slot with no stack it
   creates `cr-slot-<n>` (§6); a stack that is stale, because what the
   platform renders now has another digest than the one it was created with
   (§6, §5.3), that failed, or that runs another wargame than the pool
   assigns its number, is deleted and created again. The refill waits for
   every node to report ready and then seeds the sensor with the baseline
   rules. A slot a lease holds is not refilled; it is replaced when its
   lease closes.
8. It sends `GET /api/staff/range/` every 5 s until every slot's refill reads
   `idle`, for up to 30 min (`SLOT_WAIT`). A refill that reads `failed`
   stops `up`, which prints each slot's reason, for example a role image
   Glance does not hold active ("no active image ... in Glance") or a node
   whose boot failed; the next `up` owes that slot a refill again.

`down` does these steps:

1. It asks the VM over ssh whether a running `cr-platform` container or a store
   file exists. The store file is `db.sqlite3` in the `cr_platformdata` volume.
2. If neither exists, as after a first boot that never started the platform,
   there is nothing to back up and no platform to ask. `down` then deletes the
   range stacks with the CLI (below), the servers of step 7 and the stack.
3. If ssh does not answer, or Docker does not, `down` cannot tell. It refuses and
   deletes nothing.
4. If a store file exists beside a stopped platform container, `down` starts the
   container, because the backup runs through `docker exec`. It refuses, and
   deletes nothing, when the container does not start.
5. It keeps the range key and backs up the store (`bin/backup --keep`,
   `backups.keep`).
6. It waits for the API. Then it runs `DELETE pool/`, which drops the owed
   refills and deletes every slot stack, waits until `GET pool/` lists no
   slot with a server (up to 30 min), because each range VM's control port
   holds `cr-mgmt`, and runs `DELETE fabric/`.
7. It deletes every server whose name starts with `cr-build-`, which carries the
   `cr_image` property and which has a port on this stack's own network (the
   stack's `network` resource): a builder the VM range of before may have left.
   Such a port would make the stack delete fail.
8. It deletes the stack.

A `*_FAILED` stack has no platform to ask, and neither has step 2. For them,
`down` deletes the Heat stacks tagged `cr-range` with the openstack CLI
(`openstack stack delete --wait`), then those servers and the stack; the
fabric stays.

We ran `down` on 2026-10-11, on the VM range of before. It took 26 s. It left
no stack, builder, range network, port, router or range security group. It
kept the Glance images, the reserved floating IP, the `fsl-claude` keypair and
the `cr-build` group.

On 2026-10-20 a `down` beside a stopped container took 40 s and wrote a backup
of 430,080 bytes that passed `PRAGMA integrity_check`. An `up` after `down`
restores the newest backup that holds rows (§5.3).

If a stack is not `*_FAILED` but its `address` output cannot be read, `up` and
`down` refuse and delete nothing.

### 5.3 Rebuild and delete — lossless

```bash
uv run bin/platform-rebuild    # --cloud PATH, --ref REF, --sideload NAME=TARBALL
```

This command replaces the platform VM without losing data. It does these steps:

1. It refuses unless every image `images.yml` publishes (`platform`, `board`,
   `corp`, `corp-db`) is public on GHCR for the
   ref's commit, except the ones it sideloads.
2. It keeps the range key (`keys.range`), which it takes once from the running
   platform.
3. It backs up the store with `bin/backup`. If the old VM holds a store but its
   `cr-platform` container is stopped, it starts the container first. If the old
   VM has neither a running `cr-platform` container nor a store file, it says so,
   skips the backup and makes the range key if it is missing. If ssh to the old VM
   does not answer, it refuses.
4. It deletes and recreates the stack.
5. It waits for the new VM's cloud-init and refuses when `cr-platform.service`
   is not active, naming `cloud-init status --long` and
   `journalctl -u cr-platform`; nothing is stored on that VM yet, so
   `bin/cloud up --replace` makes it again.
6. It starts the `cr-platform` container on the new VM if it is stopped, then
   writes the kept key to `/data/ssh/id_ed25519` through `docker exec`.
7. It restores the store.
8. It writes the password into `/opt/cr/openstack-password` in place, so the
   file keeps mode 0600 and its owner. It drops a `CR_OPENSTACK_PASSWORD` line
   an older hand-over left in `/opt/cr/openstack.env` and writes the
   `CR_SIDELOADED` line there when the run sideloads; that file keeps every
   other line and mode 0600. It recreates the platform container, which reads
   the password file at start.
9. It waits for `/api/auth/csrf/`, which answers before anyone signs in.

The password file marks a finished hand-over, so it is written after the store
is in place.

There may be no store to carry over: there may be no stack, the stack may have
failed, or the VM may hold none. The backup just taken may also hold no rows. In
these cases the command restores the newest `backups/db-<UTC time>.sqlite3` that
holds rows, and names it. If there is none, the platform starts empty and says
so. The hand-over that `up` redoes (§5.2) does the same when the VM holds no
store.

Because the key is carried over, the fabric's `cr-platform` keypair stays valid.
You do not need to tear the range stacks down: no range VM has a port on the
platform stack's own network. A range stack stands through the replace when
what the new platform renders for it has the same digest (§6), and the
refill `bin/cloud up --replace` owes it then only seeds its sensor again. The digest holds the
platform's `cr-mgmt` address, which every node's user data names as its log
collector and time source. That address stays: the old VM's
`cr-platform.mgmt` port is left detached when its server is deleted, and the
fabric attaches that port to the new VM instead of making another (`_attach`
in `platform/range/openstack.py`), so the stacks stand through. On the Heat
range the platform VM's part of `bin/cloud up --replace` took 8 to 9 min in
each of five runs (2026-11-18, `docs/state/now.md`); on the range host of
2026-11-17 a replace that kept the range took 10 min 14 s and one that
replaced it 25 min 27 s (`docs/DECISIONS.md`, 2026-11-17).

`bin/backup` works like this:

- It writes a compacted copy of the store into a temporary file inside the
  platform container, using SQLite's `VACUUM INTO`. It streams the copy over ssh
  in 1 MiB chunks. It gives up only after 600 s with no data.
- When the copy passes `integrity_check`, it removes older
  `backups/db-<UTC time>.sqlite3` files beyond `--keep` (default 1, counting the
  new one). If the store held no rows, as a new VM's does, it removes none. It
  never removes a file with any other name.
- `bin/platform-rebuild` and `bin/cloud down` pass `backups.keep` from
  `cloud.yaml` as `--keep`.
- The new VM holds one copy in `/opt/cr/backups`, the one it was restored from.

The store stays small. Each request for a new allocation first deletes
allocations that were closed more than `CR_RETAIN_CLOSED_MINUTES` ago, with
their rounds, records and events, one per transaction
(`platform/training/round/retention.py`;
`manage.py prune` does it by hand). The default is 60
(`platform/cr/settings.py`, set in `compose.yaml`, overridden in
`/opt/cr/.env`). It never touches open leases. A backup therefore carries
about an hour of closed leases plus the open ones.
The store is copied back with `scp` and put in place while the platform is
stopped.

**An unpushed commit (`--sideload NAME=TARBALL`).** Sideloading means loading a
Docker image from a tarball instead of pulling it from GHCR. Both
`bin/platform-rebuild` and `bin/cloud up` take the flag, once per image.

1. The VM clones `platform.ref`, a pushed commit whose images GHCR has. It
   starts that commit as usual.
2. The rebuild copies this checkout's HEAD as a git bundle and checks it out in
   `/opt/cr`.
3. It runs `docker load` on each tarball and tags the image with the cloned
   commit (`CR_IMAGE_TAG` in `/opt/cr/.env`).
4. It stops the platform for the restore.
5. It recreates every service with `docker compose up -d --force-recreate`.
   HEAD's compose file may add services. A file bind-mounted into a running
   container, such as `filebeat.yml`, keeps the cloned commit's copy until the
   container is recreated.

`CR_IMAGE_TAG` stays what the clone gave it. A sideloaded image is loaded on
the platform VM only: the range VMs boot from the baked Glance images, and the
target's board and corp images are the ones pulled at bake (§3.6), so a
sideloaded `board`, `corp` or `corp-db` never reaches the range; push the
commit, let `images.yml` publish its images, bake the target again at that
commit and name it in `compute.target_tag` (§3.6, §4). The
rebuild still writes `CR_SIDELOADED=<names>` in `/opt/cr/openstack.env`, and a
hand-over that `up` redoes on a standing VM keeps the line. To see the names,
run `sudo docker exec cr-platform env | grep CR_SIDELOADED` on the VM.

A new bake reaches the range through `POST pool/` once `compute.images`
names it (and, for the target, `compute.target_tag` its commit): the stacks'
digest changes, so every stack is stale, and the refill `POST pool/` owes
each slot no lease holds deletes its stack and creates it again from the new
images, then seeds its sensor (§6). A stack a lease holds is replaced after
its close. `bin/cloud up` sends `POST pool/` and waits. By hand, signed in as
in §5.6:

```bash
P=http://ADDRESS:8000/api/staff/range
curl -s -b jar -c jar -H "X-CSRFToken: $(awk '$6=="cr_csrf"{print $7}' jar)" -X POST $P/pool/   # owes every free slot a refill
curl -s -b jar $P/            # slots[].refill.state: running, then idle (or failed with its reason)
curl -s -b jar $P/pool/       # each slot stack's servers, blocked and failures
```

Before it deletes anything, the command refuses in these cases:

- an unknown name
- a name given twice
- a missing tarball
- a tarball that does not hold exactly one `ghcr.io/nekonic/cr-NAME:<commit>`
- an image whose build context in `.github/workflows/images.yml` differs between
  the commit it was built from and HEAD. The built-from commit is the tarball's
  tag, or the cloned commit for an image that is pulled.

Build a tarball on any x86_64 Docker host from a clean export of the commit:

```bash
git archive $C platform | tar -x -C ctx
docker build --platform linux/amd64 -t ghcr.io/nekonic/cr-platform:$C ctx/platform
docker save -o cr-platform-$C.tar ghcr.io/nekonic/cr-platform:$C
uv run bin/cloud up --replace --sideload platform=cr-platform-$C.tar
```

Every other image goes the same way. The refusal names every image whose build
context differs from HEAD.

A sideloaded VM that reboots runs `cr-platform.service` again. Its `compose
pull` can replace the sideloaded images with GHCR's for the same tag. Push and
rebuild instead of rebooting it. MicroK8s calls importing images from `.tar`
archives without a registry "Image side-loading"
(https://canonical.com/microk8s/docs/sideload).

**Runs 2026-10-15, on the VM range of before.** We ran `bin/cloud up
--replace --sideload platform=... --sideload gns3=...` over `dev`, untouched.
Both runs exited 0. Both ranges were READY and no session was open before
each run.

- Run 1 ran `dev`'s HEAD from the previous platform VM.
- Run 2 ran HEAD with the backup fix that run 1's `bin/verify` found, from
  run 1's VM.
- The platform image was built from each HEAD. The gns3 image was built from
  an earlier commit whose `deploy/gns3` is the same.

| Stage | Run 1 | Run 2 | Evidence |
|---|---|---|---|
| Refusal checks, GHCR, bundle | 15 s | 13 s | 5 images public; contexts equal |
| Backup (`bin/backup` over ssh) | 12 min 8 s | 7 min 50 s | 5,957,828,608 bytes, integrity_check ok; 1,878,072 detections |
| Stack delete, create | 10 s, 23 s | 10 s, 22 s | reserved floating IP re-associated |
| Server created to ssh | 21 s | about 20 s | |
| cloud-init, `cr-platform.service` | 2 min | 2 min | done, no errors; `python3-venv` 3.12.3, `nodejs` 18.19.1; `/etc/sysctl.d/90-cr-syslog.conf` applied (`net.core.rmem_max = 33554432`) |
| HEAD bundle, two tarballs loaded | 2 min 29 s | 1 min 4 s | 111 MB and 241 MB; the containers run images labelled with HEAD and the earlier commit |
| Password, range key | 1 s | 1 s | key fingerprint unchanged |
| Store upload (`scp`) | 30 min 41 s | 14 min 39 s | 3.1 and 6.8 MB/s |
| Restore, `compose up -d`, API | 1 min 3 s | 1 min 4 s | migrate: no migrations to apply (the store was already at 0026); 0020-0026 `[X]` |
| Fabric, images, slot, configure, ready (the VM range of before) | 5 min 14 s | 46 s | no drift; run 1 rebuilt `cr-wargame-host` for the new tag (3 min 43 s); both ranges READY on the same servers |
| Total | 54 min 33 s | 28 min 18 s | |

Security group `cr-platform`: 22, 8000, 8002, 3080 and ICMP. After each run a
board session (497, 514) opened in about 5 s. Its map pane (now Map) drew the
learner map from `cr-gns3` with every link end green. Its close reset the
session's range to READY within 2 minutes. The old VM's Elasticsearch data does not move. Only
the store does.

### 5.4 The rename cut-over

On 2026-11-13 every name the code gives the cloud moved from the prefix `fsl` to
`cr` (`docs/DECISIONS.md`, 2026-11-13). A cloud brought up before that still
runs the old names: stack `fsl-platform`, `/opt/fsl`, the volume
`fsl_platformdata`, range servers, networks and groups named `fsl-*`. The renamed
code cannot see them, so take them down with the code that made them, once:

1. Push the renamed code to `dev` and wait for `images.yml`. Make the new
   packages public (README, "Package settings"): `cr-platform`,
   `cr-board`, `cr-corp` and `cr-corp-db`.
2. Check out the last commit before the rename beside this checkout, give it
   the current `cloud.yaml` and take the cloud down from there. `down` backs up
   the store into that checkout's `backups/`, deletes the range, the fabric,
   the builders and the stack, and keeps the floating IP and Glance:

   ```bash
   git worktree add ../cr-cutover <the commit before the rename>
   cp deploy/openstack/cloud.yaml ../cr-cutover/deploy/openstack/
   (cd ../cr-cutover && "$OLDPWD/.venv/bin/python" bin/cloud down)
   mkdir -p backups && cp ../cr-cutover/backups/db-*.sqlite3 backups/
   ```

3. Delete what `down` leaves under the old names: the role images, the
   OPNsense image and the builders' security group. Keep `fsl-claude`. The
   range VMs boot from the baked `cr-<role>-bake1` images instead (§3.6).

   ```bash
   .venv/bin/openstack image delete fsl-kali fsl-waf fsl-wargame-host fsl-opnsense-<version>
   .venv/bin/openstack security group delete fsl-build
   .venv/bin/openstack server list --name '^fsl-'; .venv/bin/openstack network list --name fsl-internet
   .venv/bin/openstack keypair list
   ```

   The server and network lists are empty and the keypairs are `fsl-claude`
   alone when the old range is gone.
4. In `cloud.yaml` set `platform.stack: cr-platform`.
5. Bring the cloud up from this checkout: `uv run bin/cloud up`
   (the scripts find `openstack` beside the Python they run under, §5.2). `platform.ref`
   must be a ref name with no `/` in it; push a branch so named if the working
   branch has one. It creates `cr-platform`, restores the newest backup in
   `backups/` and builds the fabric and the range stacks under the new names.
6. Point the `cloud` git remote at the new checkout path:
   `git remote set-url cloud ssh://ubuntu@ADDRESS/opt/cr`.

If step 2 is skipped while `platform.stack` still names `fsl-platform`,
`bin/platform-rebuild` and `bin/cloud down` find the store under
`fsl_platformdata` and refuse instead of deleting the old VM.

### 5.5 From the range host to the Heat range

From 2026-11-13 to 2026-11-18 the range was one VM, the range host `cr-range`
(`dba.range`, 6 vCPU, 16 GB), which ran range N as the Docker Compose project
`sN`; before it, each session's range was four VMs booted from role images
the platform built on builder VMs, with an OPNsense edge. A cloud that still runs either
moves to the Heat range with one `bin/cloud up` on the new code:

1. Bake the four role images (§3.6). `cloud.yaml` needs no edit: the keys the
   range host used (`network.estate`, `network.mtu`, `compute.slots`,
   `compute.flavors.range`) are read and ignored, and `compute.pool`,
   `compute.flavors.<role>`, `compute.images.<role>` and `compute.target_tag`
   default to `{board: 3, corp: 1}`, `dba.small`, `cr-<role>-bake1` and the
   commit `cr-target-bake1` was baked at (§4).
2. Run `uv run bin/cloud up --replace`. The platform VM is replaced with its
   store and range key (§5.3). `POST fabric/` makes the group `cr-senders`.
3. Before the range stacks, the same `up` sends `DELETE leftovers/`, because
   the range host holds the quota the range VMs need. It removes:
   - the range host and the VMs of the range before it, found by their
     `cr_host` metadata, and any builder (the `cr_image` metadata), waiting
     until Nova has deleted them
   - the ports the range host left on `cr-mgmt` and the ports, subnets and
     networks of the segments the fabric no longer carries (`cr-internet`,
     `cr-estate` and their `-N` copies)
   - the security groups `cr-range` and `cr-build`
   - the project's images carrying the `cr_bundle` property: the role images of
     the VM range (`cr-kali`, `cr-waf`, `cr-wargame-host`) and
     `fsl-opnsense-<version>`
   - range stacks numbered beyond the pool
4. `POST pool/` then owes every slot a refill, which creates the pool's
   stacks and seeds their sensors.

The side split's staff API has no read-only listing of leftovers; the old
tree's `GET /api/range/leftovers/` is gone. The base image, the Kali base and
the baked role images carry no `cr_bundle`, so they stay.
**(this cloud)** The switch ran on 2026-11-18: the range host `cr-range` is
deleted and the pool's four stacks stand (`docs/state/now.md`).

### 5.6 Sign-in and the stack's credentials

Every `/api/` endpoint but the sign-in routes needs a signed-in session
(Django's session cookie, `cr_session`) or, for a bot seat, its seat token
(`Authorization: Bearer`). The first migration of a store
(`accounts.0002_first_account`) makes the staff account `admin` with the
password `123456` when none exists; nothing asks for it to be changed. To
change it:

```bash
sudo docker exec -it -u cr cr-platform python manage.py changepassword admin
```

A script signs in over REST: `GET /api/auth/csrf/` sets the CSRF cookie
`cr_csrf`, and `POST /api/auth/login/` with `{"username", "password"}` and
that cookie's value in the header `X-CSRFToken` opens the session; every
POST, PUT and DELETE sends the current `cr_csrf` value as `X-CSRFToken`.
`bots/signin.py` does this through `bots/rest.py` for `bin/cloud`,
`bin/record-probes`, `bin/acceptance`, `bin/verify` and `test/`. They sign in
as `CR_ADMIN_USER` / `CR_ADMIN_PASSWORD`, by default `admin` / `123456`. With
curl:

```bash
curl -s -c jar http://$ADDRESS:8000/api/auth/csrf/ >/dev/null
T=$(awk '$6=="cr_csrf"{print $7}' jar)
curl -s -b jar -c jar -H "X-CSRFToken: $T" -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "123456"}' http://$ADDRESS:8000/api/auth/login/
curl -s -b jar http://$ADDRESS:8000/api/staff/range/
```

`/kibana/` and port 8002 ask nginx's `auth_request` to `/api/me/` first, so
the same session opens them; nginx keeps the answer for five seconds per
session cookie and client address (`proxy_cache signed_in`), so a page that
loads a hundred assets asks Django once. `/vm-terminal/<side>/<round>/` asks
`/api/rounds/<round>/terminal-auth/<side>/` instead, uncached, so it opens
only for the user holding that seat of that round while the round runs.
Signed out, port 8002 redirects to the console's `/login/` with the site
address as `next`, and the console returns there after sign-in. The two
origins are `CR_CONSOLE_ORIGIN` and `CR_SITE_ORIGIN` in `compose.yaml`
(unset: `http://<asked host>:8000` and `:8002`); behind a TLS reverse proxy
or a domain set both, as `https://cr.example`, scheme, host and port only.

Elasticsearch and Kibana run without security. They listen on the platform
VM's loopback only (127.0.0.1:9200 and 127.0.0.1:5601), and the range has no
route to them. Through `/kibana/`, nginx refuses Kibana's API outside a space
and the default space, sends the management and dev tools pages to Discover,
and hands every API call inside a space to the platform's `/kibana-gate/`,
which refuses a space the user holds no defence seat for and any call
`defence/kibana.py`'s `refusal` does not allow (a JSON 403 with a Korean
message from `strings/server.json`); a path nginx itself refuses is answered
by the same gate. An operator
reaches Elasticsearch and Kibana over an ssh tunnel.

## 6. The range (substrate openstack)

Everything goes through the platform's staff range API, as `fsl-range`; a
staff session calls it (`match/views.py`, tag `staff`).

- `GET /api/staff/range/` lists each slot, its wargame, the lease that holds
  it and its refill state; `GET pool/` each slot stack's servers, what
  blocks it and its failures.
- `POST` makes the cloud match the plan: `fabric/` at once, `pool/` by
  owing each free slot a refill the `rebuild` service carries out.
- `DELETE` tears down. A range not built through OpenStack answers
  `409 range_not_cloud`.

`bin/cloud up` runs these calls in order. By hand, signed in as in §5.6 (each
write sends `-H "X-CSRFToken: $T"`):

```bash
P=http://$ADDRESS:8000/api/staff/range
curl -s -b jar -H "X-CSRFToken: $T" -X POST $P/fabric/      # cr-mgmt (DHCP on, no gateway), keypair cr-platform,
                                  # groups cr-reach/cr-mgmt/cr-egress/cr-senders, platform port cr-platform.mgmt
curl -s -b jar -H "X-CSRFToken: $T" -X DELETE $P/leftovers/ # what the ranges before this one left (§5.5)
curl -s -b jar -H "X-CSRFToken: $T" -X POST $P/pool/        # every slot no lease holds owes a refill: create a missing stack,
                                  # delete and create again a stale or failed one, wait for its nodes, seed its sensor
curl -s -b jar $P/                # slots[].refill.state running, then idle, or failed with its reason
curl -s -b jar $P/pool/           # slots[].servers, blocked, failures
```

Notes:

- The platform finds the fabric's network by the tag `cr.segment.id=mgmt`, not
  by name. The fabric needs the Neutron `standard-attr-tag` extension, which is
  on by default. A network of any other segment, or of a `cr.slot` tag other
  than 1, is listed as a leftover.
- The platform finds the range stacks by the Heat tag `cr-range` and tells them
  apart by `cr.slot=<n>`, the stack number N (see the glossary in
  `docs/ARCHITECTURE.md`); `cr.wargame=<w>` says which wargame a stack runs and
  `cr.digest=<d>` what it was rendered from (the template and the role images'
  and flavors' names, and `compute.target_tag`). A stack whose digest differs
  from what the platform renders now is stale. A stack beyond the pool's count
  is a leftover. Which wargame a stack runs comes from the pool's assignment
  of its number (§6.4), not from the tag: a free stack that runs another
  wargame is replaced.
- A slot with no stack is blocked, before Heat is asked, when Glance holds no
  active image of a role's `compute.images` name ("no active image ... in
  Glance"), when the platform has no `cr-mgmt` address, or when no wargame has
  a `topology.yaml`; `GET pool/` lists the reason under `blocked`, and the
  slot's refill fails with it.
- Every node's user data ends with `systemctl start` of its role's boot units
  (`BOOTS` in `platform/range/stack_plan.py`: kali `slot-boot`; waf `slot-boot`
  and `nginx`; infra `slot-boot` and `sensor`; target `wargames`), then
  touches `/var/lib/cr/ready`, or writes the units' status into
  `/var/lib/cr/failed`. Two nodes check more first. The target refuses ready
  when an `image:` line in `/opt/wargames/*/compose.yaml` carries another tag
  than `compute.target_tag`, and writes those lines into `failed`; a line
  pinned by digest (`@sha256:`, the databases) passes. The infra
  reports ready only once `suricatasc -c uptime` answers (its node's
  `answers:` in `topology.yaml`, tried for up to 300 s), because configure
  loads the baseline rules through that socket next. The platform asks each
  node over ssh and reports it
  `SETTING_UP` until one of the two exists. `GET pool/` names
  `/var/log/cloud-init-output.log` under `failures` for a node that failed,
  and a stack Heat reports `CREATE_FAILED` with Heat's reason. A refill
  (`range/refill.py`, advanced by the `rebuild` service) calls `ensure_slot` in
  `platform/range/openstack.py`, which deletes a failed or stale stack, or
  one that runs another wargame than the pool assigns, and creates it again,
  then `configure_slot`, which seeds the sensor. A refill that is blocked,
  whose stack still fails, or that has not created and set up its stack
  within 30 min reads `failed` with the reason, and `bin/cloud up` stops on
  it. Only `POST pool/` and a lease's close owe a slot a refill, and
  `POST pool/` skips every slot an open lease holds.
- The platform reaches each range VM as `CR_OPENSTACK_SSH_USER` (`ubuntu`) on
  its control port on `cr-mgmt`, with the range key and one shared ssh
  connection per address (`ControlMaster auto`, `ControlPersist 60`). Each
  node's user data creates that user with the platform's public key and
  passwordless sudo, after cloud-init's default user; on Kali the default user
  `kali` stays for the learner's ssh (§3.5). A role a container fills (the
  target's `board`, `board-db`, `corp-wp`, `corp-db`, and the infra's Suricata
  sensor `sensor`) runs its command with `sudo docker exec <container>` on its
  VM; every other role runs on its VM with `sudo`. Once every node of a `CREATE_COMPLETE` stack is ready, the
  platform keeps their `cr-mgmt` addresses and host-key aliases for that stack
  id in the API server's memory, so a command asks the cloud nothing; creating
  or deleting the stack drops them.

**The range stack.** Stack N is the Heat stack `cr-slot-<n>`. `platform/range/stack_plan.py`
turns `wargames/<w>/topology.yaml` and the declaration's origins into a plan,
and `platform/range/openstack.py` renders it as a Heat Orchestration Template
(`template()`) and creates the stack with `disable_rollback` and a 30-minute
timeout. The stack's parameters are the fabric's keypair, network and groups,
each role's image and flavor (`compute.images`, `compute.flavors`), and each
LAN's `cr-lan-` group (`group_<lan>`). Every
stack uses the same addresses; stacks differ by network, not by CIDR.

| LAN (`cr-slot-<n>-<lan>`) | Subnet | Members |
|---|---|---|
| `internet` | 121.134.88.40/29 and the default origin's /24 (5.188.10.0/24) | Kali (5.188.10.10, the pair `0.0.0.0/0`); the infra's `wan` 121.134.88.42 |
| `dmz` | 10.30.0.0/24 | the infra's `lan` .1 (the pair `0.0.0.0/0`, since it routes); the WAF's front .247 |
| `web-outer` | 10.30.128.0/24 | the WAF's back .247; the infra's IDS leg A .251, port security off |
| `web-inner` | 10.30.128.0/24 | the target, board .59 or corp .60; the infra's IDS leg B .252, port security off |
| `mgmt` | 172.29.0.0/24 | the infra's log server .10; the WAF's mgmt .12 |

| VM (`cr-slot-<n>-<node>`) | Image | Learner |
|---|---|---|
| `kali` | `cr-kali-bake1`: Kali with `kali-linux-headless` and the tools; rebaked with the infra (§3.8) | `kali` with passwordless sudo, by the attack seat's web terminal and its jump grant (§3.5) |
| `waf` | `cr-waf-bake1` (**(this cloud)** `cr-waf-bake2`): Ubuntu, nginx 1.24, ModSecurity 3.0.16, CRS 4.25.1 | the defence seat as `analyst`, by web terminal and its jump grant (§3.7); the image must be rebaked for the split site config and the writable defence files |
| `infra` | `cr-infra-bake1`: Ubuntu, nftables, Suricata (`jasonish/suricata`, pinned by digest), rsyslog; the image must be rebaked for the customers program (§3.8) | none |
| `target` | `cr-target-bake1`: Ubuntu, Docker, board and corp at the baked tag | none |

- The subnets have DHCP off and no gateway, and no Neutron router stands on any
  of the stack's LANs. Every port has a fixed IP; the VMs boot with a config drive, whose
  `network_data.json` cloud-init configures the NICs from. Nova refuses a port
  without a fixed IP, so the IDS legs hold the dummy addresses .251 and .252,
  which the infra's boot flushes.
- Each node also has a control port on the fabric's `cr-mgmt`, in the group
  `cr-mgmt`; the infra's is also in `cr-senders`, the only group the collector
  takes udp 5140 from (§3.5). Both groups send only to the platform's
  `cr-reach` and to DHCP, so no range VM reaches the metadata address
  169.254.169.254 (§3.5).
- Each LAN's secured ports are in a security group that admits in from the
  LAN's subnets, from anywhere on a LAN where a port carries an address pair
  (`internet`, `dmz`), and on `mgmt` only tcp 514 from its subnet. Every stack
  uses the same addresses, so every stack has the same rule sets, and LANs with
  equal rules share a group. The adapter (`lan_groups` and `_lan_group_ids` in
  `platform/range/openstack.py`) makes each group `cr-lan-<digest>` once, under
  a lock, before it creates a stack, and hands their ids to the stack; board
  and corp take the same three (§3.5). The rules name CIDRs, not groups, and
  each stack's LANs are networks of its own, so a shared group opens nothing
  between stacks. Neutron enforces these outside the guest, so root in Kali or
  the WAF cannot change them. The pair `0.0.0.0/0` lets Kali send from any origin address; port
  security still binds Kali's port to the MAC Neutron gave it.
  `max_allowed_address_pair` is 10 on this cloud, so the 30 origin /24s cannot
  each be a pair.
- Kali's `slot-boot` adds the other origin addresses (about 100 over the 30
  origin /24s, the default origin's first) and a default route onlink via
  121.134.88.42. Kali resolves only `board.com` and `corp.com`, both to that
  address.
- The infra is the edge router, the IDS and the log server. Its `slot-boot`
  bridges the two IDS legs into `br0`, flushes their addresses and switches
  TSO, GSO, GRO and LRO off on them; sets a default route onlink via Kali's
  default-origin address; and loads `edge.nft`: tcp 80 to 121.134.88.42 is
  DNATed to the WAF's front without SNAT, from `wan` an address in the set
  `spent` is dropped first, then every address outside `pool`, then only replies
  (`ct state established,related`) and DNATed connections (`ct status dnat`)
  are forwarded, ICMP is answered on `wan`, and from `mgmt` only tcp 514 is
  taken. Ping and traceroute from Kali to 121.134.88.42 answer.
- The sensor is inline: Suricata (`sensor.service`, the pinned image on the
  host network) captures on `br0` with `af-packet`, so it sees the WAF to the
  web servers, with `X-Forwarded-For`. A request the WAF blocks never reaches
  it; the WAF's own logs record it. The config is
  `deploy/suricata/suricata.yaml`; EVE has `xff` on (`mode: extra-data`,
  `deployment: reverse`), so ingest credits each alert to the client's address
  (`docs/ARCHITECTURE.md`, the alert path). The rule file is
  `/var/lib/suricata/rules/local.rules`, reloaded with `suricatasc -c
  reload-rules` (the device `cr-ids` in the topology). `cr-ids` names
  `container: sensor`, so rule validation (`suricata -T`), reading and writing
  the rule file and the reload all run through `docker exec sensor` on the
  infra; the host has only the `suricatasc` wrapper.
- The WAF's `slot-boot` routes it through the infra's `lan`, writes `board`
  and `corp-wp` into `/etc/hosts` with the target's addresses, and ships
  ModSecurity's audit log and nginx's JSON access log of every request
  (`/var/log/modsecurity/audit/audit.log`, `/var/log/nginx/access.json`) with
  rsyslog's `imfile` over tcp 514 to the infra's log server on `mgmt`. The
  exclusion file is
  `/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`,
  reloaded with `nginx -t && nginx -s reload` (the device `cr-waf`).
- The infra's rsyslog relays the WAF's lines and its own EVE to the platform's
  collector, udp 5140 over `cr-mgmt`, under the sender names `waf-<n>` and
  `infra-<n>`; the collector writes stack N's lines to `logs-N-*`.
- The target VM runs the stack's wargame (`WARGAMES` in `/etc/slot.env`) with
  Docker Compose from `/opt/wargames/<w>/compose.yaml`, rendered at bake: the
  front publishes on the target's `web-inner` address (board 8000, corp 80), the
  database stays on the internal network `<w>_backend`. `wargames up` restores
  the pristine data kept at bake into empty volumes before it starts them. The
  ground truth of the board (`/internal/auth-users`) is read inside the board
  container through the `board` role, and corp's effect reader gets
  `corp-db`'s binary log the same way.
- Every node takes its time from the platform's `cr-mgmt` address through a
  `systemd-timesyncd` drop-in (`/etc/systemd/timesyncd.conf.d/60-cr.conf`) its
  user data writes.
- The learner map is read from Neutron: the stack's networks and ports by the
  tag `cr.slot=<n>` (`range/wiring.py`; the control ports are left out), and the database zone from the target
  VM's internal Docker networks (`docker network inspect` over ssh, once per
  held stack), drawn as `<w>-backend`.

The refill's last step seeds each stack's sensor with the baseline rules
(`deploy/suricata/rules/local.rules` from the platform's checkout) through
`rules.suricata.seed`; a round's start then applies its problem's posture
over it. Everything else a stack needs is in its images and its user data.

Secrets stay per round. The board's `seed` sets each seeded account's
fixed password on every start, the image default; each round's start then
runs the board's `set_passwords` inside the board container (§3.9), so
every round's hashes come from new random passwords. corp's
entrypoint deletes `wp-config.php` before the WordPress image's entrypoint
runs, which then writes new random keys and salts, and on restored data it
sets the admin password again.

The seats' web terminals (`/vm-terminal/<side>/<round>/`, which nginx hands
to `platform/vm-terminal.sh cr-kali attack <round>` or `cr-waf defence
<round>`) ssh to the VM's control address as the management user and run
`sudo -i -u kali` on Kali or `sudo -i -u analyst` on the WAF, never a root
shell; the script opens only for a seat whose round is running and which
holds a jump grant, and closes the shell within `TERMINAL_RECHECK` seconds
(15) once that no longer holds. A seat's own ssh goes through the jump in
the platform container (§3.5). The learner on Kali has passwordless sudo, so
the attack seat is root there all the same.

### 6.1 Slot refill

A lease (`POST /api/leases/`) is given a slot that no open lease holds, that
the pool assigns to its wargame and whose refill is `idle`; the choice runs
under one lock. When there is none it answers `503 range_unavailable` with
`retry_after`. No slot of another wargame is retargeted.

Closing a lease, by its operator or because no heartbeat came for
`CR_LEASE_IDLE_MINUTES` (30), ends its open rounds, deletes its stack and
owes the slot a refill: the `rebuild` service creates the stack again for the same
wargame, off the learner's path, and seeds its sensor. Every VM of the next
lease is new, booted from the baked images, with the target's pristine data;
what a round disabled or applied went with the old stack. Acceptance checks
that after a close the stack's WAF has another boot id and lacks the file the
last learner wrote.

A restart of the platform or the `rebuild` service does not lose a refill: its state
is a file per slot under `CR_REFILL_DIR` (`/data/refill`, `slot-N.json`),
and the `rebuild` service picks every running one up on its next pass. A refill whose
stack is not created and set up within 30 minutes reads `failed` with the
reason in `GET /api/staff/range/`; `POST pool/` owes it again.

How long a stack takes to delete and to come back ready, so how long a stack
is away after a close, is **[unverified]**. The probe stack of 2026-11-18 (three
Ubuntu VMs on `dba.small`) reached `CREATE_COMPLETE` in 29 s and answered ssh
about 1 min 53 s after. The first pool fill of 2026-11-18 created the four
stacks at once with no image cached on com01: the 14 GB Kali image was copied
to com01 first, the other VMs were `ACTIVE` after about 4 to 5 min, and the
stacks reached `CREATE_COMPLETE` after about 12 to 13 min. The infra wrote
ready about 3 min after its boot, the target about 2.5 min after (cloud-init
finished at 151 s).

### 6.2 Teardown order

Delete the range stacks, then the fabric. `DELETE $P/pool/` drops every owed
refill and deletes every slot stack; the staff API deletes no single slot (a
lease's close replaces its own). Heat deletes a stack's servers,
ports and networks itself; the `cr-lan-` groups are not the stack's and stay
for the next stack. Each range VM's control port stands on
`cr-mgmt`, so `DELETE $P/fabric/` refuses while any server other than the
platform has a port on it; `bin/cloud down` waits until `GET $P/pool/` lists
no slot with a server first. Teardown also deletes the ports that no server holds
any more. Nova leaves the pre-created `cr-platform.mgmt` port standing when it
deletes a platform VM; the next `POST fabric/` attaches that port to the new
platform VM, so the platform keeps its `cr-mgmt` address, and deletes any
further detached port of that name. `DELETE $P/fabric/` deletes the `cr-lan-`
groups after the stacks (`networks.LAN_GROUP_PREFIX`), and the groups `cr-range`
and `cr-build` if they are still there.

### 6.3 Keypair drift

The fabric compares the keypair `cr-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new key. Then
`POST fabric/` answers `503 range_drifted`, naming `keypair cr-platform holds
another public key`. The fix is to delete the range stacks and then the fabric
before you replace the VM. With `bin/platform-rebuild` the key is carried over
and nothing drifts. The public key is also in every stack's user data, so a
new key makes every stack stale.

### 6.4 The pool

`compute.pool` sets how many range stacks stand ready for each wargame; it
reaches the platform as `CR_OPENSTACK_POOL` (`board=3 corp=1`). Stacks are
numbered in the mapping's order: with the default, stacks 1 to 3 are built for
board and stack 4 for corp.

- Stack N is `cr-slot-<n>`: four VMs and five networks of its own. How many
  stacks run at once is the cloud's capacity (§3.2), not a limit in the
  design.
- The platform gives each lease a free ready stack of its wargame and keeps
  it for the life of the lease (`Lease.slot` holds its number). The close
  replaces only that stack.
- The collector writes each stack's syslog to `logs-N-*`. It tells the stacks
  apart by the sender's name (`waf-2`, `infra-2`). A lease's rounds read their
  own stack's index.

To grow the pool, raise a count in `compute.pool` and run `uv run bin/cloud up
--replace`: `POST pool/` owes the new slots a refill, which creates their
stacks. To shrink it, lower a count; `DELETE leftovers/` deletes the stacks
numbered beyond the new total. The pool's assignment decides which wargame
each number runs: when a count moves, the refill `POST pool/` owes each free
slot deletes a stack that runs another wargame and builds it for the
assigned one; a stack a lease holds follows after its close. By hand on a
standing platform:

```bash
sed -i 's/^CR_OPENSTACK_POOL=.*/CR_OPENSTACK_POOL=board=3 corp=2/' /opt/cr/openstack.env
docker compose up -d --force-recreate platform rebuild
curl -s -b jar -H "X-CSRFToken: $T" -X POST $P/pool/   # owes every free slot a refill; slot 5 is built for corp
curl -s -b jar $P/                                     # slots[].refill.state idle
```

On the VM range of 2026-10-12, two sessions of the old tree opened at once
took ranges 1 and 2, a third answered 409, and each session ingested only its
own case's alerts.

## 7. Verification

```bash
curl -s -b jar http://$ADDRESS:8000/api/staff/range/                       # signed in as in §5.6
curl -s -b jar -H "X-CSRFToken: $T" -X POST http://$ADDRESS:8000/api/staff/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/cr && CR_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` runs `uv sync --frozen` and then the checkout's
`.venv/bin/python`. The platform VM creates `/opt/cr/.venv` with uv at first
boot (§5.1), and again after a sideload checkout. `bin/verify` restarts the
platform and prunes leases, and the acceptance suite opens and closes its
own leases, each close replacing a stack. Never run it against a stack that
someone is using.

`bin/verify --changed --live` runs only the acceptance modules that a change
reaches (`bin/acceptance --only`). `--fast` runs no acceptance.

Since 2026-10-17 the whole acceptance suite runs here (`docs/DECISIONS.md` "No
acceptance test is skipped on OpenStack"). Two full runs of the old tree were
made on the Heat range (2026-11-18); their numbers and causes are in this
file's and `docs/state/now.md`'s git history. The side split's ported suite
(`test/`, on the generated client; `test_lesson.py`, `test_ready.py` and
`test_map.py` dropped, `docs/DECISIONS.md` 2026-11-20) has not run on a
cloud yet (`docs/STATE.md`).

A change to a range VM role (`deploy/roles/<role>/` or a file it links, such as
`deploy/kali/`, `deploy/proxy/stamp.py`, `deploy/waf/`, `deploy/suricata/` or a
wargame's `compose.yaml` and app image) reaches the range only through a new
bake (§3.6). Range VMs boot from the Glance images `compute.images` names, and the
stack's digest covers those names and the flavors, not the images' content:
bake under a new name (`cr-<role>-bake2`), name it in `compute.images` (a
target bake also its commit in `compute.target_tag`), and with the new names
`bin/cloud up --replace` finds every stack stale; each stack no lease holds
is deleted and its refill builds it again. A change that alters the rendered template does the same
without a bake: `wargames/<w>/topology.yaml`, the declaration's origins, the
user data `range/stack_plan.py` writes, or the template `range/openstack.py`
renders. The sensor's rules need no bake: each refill seeds the sensor with
`deploy/suricata/rules/local.rules` from the platform's checkout (§6).

**The first acceptance run on the OpenStack substrate**, 2026-10-11, on a range
built from scratch by `bin/cloud up` on the previous cloud (OPNsense 26.7 edge):
50 passed, 86 skipped, 6 failed, 4 errors. The run before the reset fixes gave 24
passed, 14 failed, 22 errors. We have since fixed or deleted what that run left:

- Tests that reached compose containers (`kali`, `corp-db`) now reach the
  session's hosts through `run_on_role`.
- WAF tuning (`PUT /api/sessions/<id>/waf/`) uses the WAF host's declared rule
  file, reload command and pid (`rules/crs.py` `Layout`), not the Docker image's.
- We deleted the compose-only checks on 2026-10-17.

Run time was 2,900 s: fixture setup 1,689 s, test bodies 1,179 s, teardown 27 s.
The slowest item is `test_disabled_rule`'s setup (578 s).

We checked live the same day:

- The edge's Suricata 8.0.6 loads the `conf.d/cr.yaml` include and `cr.rules`
  (4 of 4 rules).
- `suricatasc` is at `/usr/local/bin/suricatasc` with its socket at
  `/var/run/suricata-command.socket`, as the declaration names.
- The WAN pass rule is in pf.
- All of this survives a reboot. The edge answers again in about 30 s.
- Kali on Ubuntu has mitmproxy (8.1.1), mitmdump, nikto, ffuf, gobuster, whatweb,
  dirb with its wordlists, sqlmap, nmap, hydra and nc.
- A session close resets the range (§6.1). Close to READY measured 93 s.

We did not check whether that OPNsense edge survived an OPNsense update.

## 8. Known issues

- Related sections: no resize (§2.4), the TaaS override (§2.3), no Cinder,
  keypair drift (§6.3), and the quota the pool takes (§3.2).
- On the first `bin/cloud up` on this cloud (ML2/OVN, 2026-10-20) every name
  lookup on the range VMs of that time waited about 25 s, and `POST
  /api/range/configure/` answered 409 `container corp-wp is unhealthy`. With no
  `[ovn] dns_servers`, Neutron announced `127.0.0.53`, the resolver of the
  `neutron-server` host (§2). The hosts' systemd-networkd sent that address out
  of `ens3`, so each lookup timed out (`getent` took 24.6 s). WordPress's
  healthcheck, `wp core is-installed` with a 5 s timeout, took 29.2 s.
  - Fixed: `platform/range/openstack.py` creates the `cr-mgmt` subnet with the
    DNS server `0.0.0.0`, which announces no resolver; after the fix `getent`
    failed in 0.03 s and `wp core is-installed` took 1.9 s. A range stack's
    own LANs have DHCP off and take their addresses from the config drive
    (§6). A fabric made before that fix keeps the old subnet: run `openstack
    subnet set --dns-nameserver 0.0.0.0 cr-mgmt`, then replace the range
    stacks (`DELETE $P/pool/`, then `POST $P/pool/`, §6.2) so that their VMs
    ask DHCP again.
  - A cloud admin can also set `[ovn] dns_servers`, which helps the cloud's other
    VMs. The product no longer needs it.
- A member user cannot create flavors or change quotas. Neither the
  platform's stack nor a range stack uses an admin-only Heat resource.
- `platform.ref` is required (example value `dev`; `--ref` overrides it). The VM
  sees only pushed commits.
- The project password is plain text in `/opt/cr/openstack-password` (0600,
  uid 10001) on the platform VM and in the platform container's mount of it,
  `/run/secrets/openstack_password`. It is in no container's environment.
- Kali's origin addresses exist only on its stack's `internet` LAN, a Neutron
  network with no router, so they never meet the Docker networks `compose.yaml`
  declares on the platform VM or any other stack. The platform reaches Kali only
  over Kali's control port on `cr-mgmt`, with ssh.
- The edge router holds no address on `web-outer` or `web-inner`: its two IDS
  legs are bridged and flushed (§6), so Kali reaches neither target past the
  WAF, by address or by name, as `test/test_range_isolation.py` asserts. By
  name Kali reaches only `board.com` and `corp.com`, the router's public IP,
  whose port 80 goes to the WAF.
- Fixed 2026-10-12 on the VM range of that time, after we measured it first.
  Kali had a `mgmt` port, and while every range port sat in one group an nmap
  from Kali found these open ports on `mgmt`:
  - the wargame host's 22, 80 and 8000 (`/internal/auth-users` answered 200 with
    every password hash)
  - the edge's 22, 80 and 443 (the OPNsense GUI)
  - the WAF's 22 and 80

  Today every range VM's control port on `cr-mgmt`, Kali's included, is in the
  group `cr-mgmt`, which admits only the platform's port and sends only to it
  and to DHCP (§3.5).
  `test/test_range_isolation.py` checks from Kali, the WAF and the board that none
  reaches the platform, the Internet or the metadata address; from Kali that it
  reaches the sites only through the WAF, that ping and traceroute to
  121.134.88.42 answer and a SYN scan finds the WAF's private address filtered,
  that nothing on `cr-mgmt` (every range VM's control port and the platform's)
  takes a connection, and that a frame from a MAC address Neutron did not give
  Kali's port is dropped (the pair `0.0.0.0/0` admits any source address; port
  security still binds the MAC); and that after a close the stack's WAF is a new
  VM, with another boot id, without the file the last learner wrote.
- Names on the range VMs come from the image and from `/etc/slot.env`, not from
  Neutron: Kali's image names `board.com` and `corp.com` as the router's public
  IP (in `/etc/hosts` and in cloud-init's hosts template), and the WAF's
  `slot-boot` writes `board` and `corp-wp` with the target's addresses at every
  boot.
- Operator machine on the same subnet as the cloud. Suppose the operator's
  Wi-Fi uses the same subnet as the cloud's addresses, and the cloud is reached
  over a tunnel (WireGuard or another VPN). The connected route then wins, and
  cloud addresses go out the Wi-Fi interface. Put /32 `AllowedIPs` for the cloud
  hosts in the tunnel, or run a proxy bound to the tunnel interface. Check the
  route before any cloud call.

## 9. Try it in one VM (VirtualBox or VMware)

This section is for checking that the product runs. It is not for operating it.
One Ubuntu 24.04 VM holds an all-in-one Kolla-Ansible cloud and this
repo's numbered steps. The 2026-10-20 trial ran 2026.1; the commands below use
2025.2 and were not run again. It follows the official quickstart [K1] and the
hypervisors' manuals [V1][W1]. Run end to end on 2026-10-20 (on a KVM host; the
VirtualBox/VMware settings themselves were not exercised). Nested KVM is
recommended; without it the cloud runs its VMs under plain QEMU, only slower
(§2.2).

### 9.1 The VM

- Ubuntu 24.04 Server with **8 vCPU, 40 GB RAM and a 250 GB disk** (allocated as
  needed). The 2026-10-20 trial used these sizes for the VM range of that time.
  The Heat range needs the platform VM and four VMs per range stack, so a
  one-VM trial sets `compute.pool` to one stack (`{board: 1}`, §4); what one
  stack takes on `dba.small` is **[unverified]**. The sizes come from these
  figures:
  - The platform VM needs 8 GB of RAM and 60 GB of disk with the example
    flavor (§3.2), and each range stack four times its role flavors. Nova counts RAM
    and disk one to one (`initial_ram_allocation_ratio` and
    `initial_disk_allocation_ratio` are 1.0 [N2]).
  - Kolla's own services need the quickstart's minimum of 8 GB and 40 GB [K1].
  - The rest of the disk is margin for Glance's images (the base image, the
    Kali base and the four role images, §3.6) and Nova's cache of them.
  - Nova shares CPU 4 to 1 by default [N2].
  - The host needs more than 40 GB of RAM and 250 GB of free disk.
- The whole 250 GB must reach Nova. Ubuntu's guided storage makes the root
  logical volume at most 100 GiB of a disk this large. It leaves the rest of the
  volume group unused [S1]. Nova would then see about 100 GB, and the range VMs
  would fail with `NoValidHost`.
  - In the installer's storage step, edit `ubuntu-lv` to use the whole volume
    group.
  - On an installed VM, run `sudo lvextend -r -l +100%FREE
    /dev/ubuntu-vg/ubuntu-lv`. `df -h /` then shows about 245 GB.
- Turn on nested virtualization in the hypervisor's own setting. In VirtualBox:
  Settings, System, Processor, **Enable Nested VT-x/AMD-V** [V1]. In VMware
  Workstation: Processors, **Virtualize Intel VT-x/EPT or AMD-V/RVI** [W1].
- Give the VM two network adapters on the same network. The host must reach that
  network, and it must reach the Internet.
  - VMware Workstation: set both adapters to **NAT**.
  - VirtualBox: set both to **Bridged Adapter** on the host's wired interface. On
    the second adapter, under Advanced, set Promiscuous Mode to **Allow All**
    [V1].
- The commands below use the plan in the table. Replace it with your network's
  own values. In VMware Workstation, the Virtual Network Editor shows the NAT
  subnet, its gateway and its DHCP range. The pool must lie outside the DHCP
  range.

| | Example |
|---|---|
| Network | 10.10.10.0/24 |
| Gateway | 10.10.10.1 |
| First adapter (management, fixed) | 10.10.10.10 |
| Floating-IP pool | 10.10.10.20 to 10.10.10.99 |

After the install, find the adapters' names with `ip -br link` (here NIC1 and
NIC2). Give the first the fixed address and bring the second up with no address.
Put this in `/etc/netplan/60-kolla.yaml`, then run `sudo netplan apply`:

```yaml
network:
  version: 2
  ethernets:
    NIC1:
      dhcp4: false
      addresses: [10.10.10.10/24]
      routes: [{to: default, via: 10.10.10.1}]
      nameservers: {addresses: [8.8.8.8, 8.8.4.4]}
    NIC2:
      dhcp4: false
      dhcp6: false
      optional: true
```

The two settings do the following:

- `dhcp4: false` on NIC1 matters because the installer's own
  `50-cloud-init.yaml` merges with this file. Without the setting, it would
  leave a DHCP address and a second default route beside the fixed one.
- `optional: true` on NIC2 keeps boot from waiting for an address that the
  adapter never gets.

Kolla-Ansible runs its playbooks with sudo, and the deploying user must not be
asked for a password. Give that user passwordless sudo:

```bash
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/90-kolla
```

Install the quickstart's packages and check whether the CPU's virtualization
reaches the VM:

```bash
sudo apt update && sudo apt install -y git python3-dev libffi-dev gcc libssl-dev libdbus-glib-1-dev python3-venv cpu-checker
sudo kvm-ok          # "KVM acceleration can be used"
```

If `kvm-ok` says KVM cannot be used, set `nova_compute_virt_type: "qemu"` in the
`globals.yml` lines below instead of `"kvm"`. The VMs then run under plain QEMU
emulation: everything works, more slowly.

### 9.2 The cloud

These are the quickstart's all-in-one steps [K1], run in `~`:

```bash
python3 -m venv ~/kolla-venv && export PATH=~/kolla-venv/bin:$PATH && pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2025.2
pip install docker dbus-python
sudo mkdir -p /etc/kolla && sudo chown $USER:$USER /etc/kolla
cp -r ~/kolla-venv/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
cp ~/kolla-venv/share/kolla-ansible/ansible/inventory/all-in-one .
kolla-ansible install-deps
kolla-genpwd
```

Append this to `/etc/kolla/globals.yml` (§2.2). The example file is all
comments:

```yaml
kolla_base_distro: "ubuntu"
network_interface: "NIC1"
neutron_external_interface: "NIC2"
kolla_internal_vip_address: "10.10.10.10"
enable_haproxy: "no"
enable_proxysql: "no"
nova_compute_virt_type: "kvm"
```

Then deploy. This step pulls the images from quay.io and is the long one. It
took 11 min 39 s on 2026-10-20. §2.1 gives the reasons for the extra `pip install`,
`--use-test-images` and `-i`.

```bash
kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one --use-test-images
kolla-ansible deploy -i ./all-in-one
pip install python-openstackclient -c https://releases.openstack.org/constraints/upper/2025.2
kolla-ansible post-deploy -i ./all-in-one
. /etc/kolla/admin-openrc.sh
```

### 9.3 The project, then this repo's steps

Stay in that shell as admin. Do these steps:

1. Create the external network on the second adapter's network, with the plan's
   subnet and pool (§2.5).
2. Create the platform flavor when the cloud has none that fits, and the range
   VM roles' flavor (§3.3). Raise the quota to the platform and four VMs per
   range stack (§3.2).

Then open a new shell, as the same user, so that the admin `OS_*` variables
from `admin-openrc.sh` are gone, and run README's install section: clone, then
`uv run bin/cloud init`, which signs in with `/etc/kolla/clouds.yaml` and makes
the project, the user and the base image, then bake the four role images
(§3.6) and run `uv run bin/cloud up`. The
clouds.yaml entry's `auth_url` is `http://10.10.10.10:5000`. The browser that
checks the result is the host's browser. It opens the floating IP that
`bin/cloud up` prints. The external network makes that address reachable on the
host's network.

## Sources

- [K1] Kolla-Ansible 2025.2 quickstart — https://docs.openstack.org/kolla-ansible/2025.2/user/quickstart.html
- [K9] kolla-ansible stable/2025.2 `ansible/post-deploy.yml` (writes `admin-openrc.sh` into `/etc/kolla`) and `ansible/roles/common/templates/admin-openrc.sh.j2` (the `OS_*` variables it exports) — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/ansible/roles/common/templates/admin-openrc.sh.j2
- [K10] kolla-ansible `ansible/post-deploy.yml`, task "Template out clouds.yaml" (`dest: "{{ node_config }}/clouds.yaml"`, mode 0600; `node_config` defaults to `/etc/kolla` in `ansible/group_vars/all/common.yml`), and `ansible/roles/common/templates/clouds.yaml.j2`, whose first entry is `kolla-admin` (Keystone's public URL, the admin user and project, domain `Default`, `region_name`); the same on stable/2025.2 and unmaintained/2025.1 — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/ansible/post-deploy.yml, https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/ansible/roles/common/templates/clouds.yaml.j2
- [K2] kolla-ansible stable/2025.2 `etc/kolla/globals.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/etc/kolla/globals.yml
- [K7] Kolla-Ansible 2025.2, Libvirt guide (`nova_compute_virt_type`: kvm is the default) — https://docs.openstack.org/kolla-ansible/2025.2/reference/compute/libvirt-guide.html
- [K8] Kolla-Ansible 2025.2, Neutron networking (`neutron_external_interface` goes on `br-ex`, physical network `physnet1`; the page says an interface plugged into a bridge cannot hold a usable IP address) — https://docs.openstack.org/kolla-ansible/2025.2/reference/networking/neutron.html
- [K3] kolla-ansible stable/2025.2 `ansible/group_vars/all/neutron.yml` (`enable_neutron_taas: false`); TaaS added in 18.0.0 — https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html
- [K4] kolla-ansible stable/2025.2 `ansible/roles/neutron/tasks/config.yml` (the 2026.1 bug in §2.3 was measured on stable/2026.1) — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/ansible/roles/neutron/tasks/config.yml
- [K5] Kolla-Ansible, OpenStack service configuration overrides — https://docs.openstack.org/kolla-ansible/latest/admin/advanced-configuration.html
- [N1] Nova configuration, `allow_resize_to_same_host` (default False) — https://docs.openstack.org/nova/latest/configuration/config.html
- [N2] Nova configuration, `initial_cpu_allocation_ratio` 4.0, `initial_ram_allocation_ratio` 1.0, `initial_disk_allocation_ratio` 1.0, `reserved_host_memory_mb` 512 — same page
- [N3] Neutron, DNS resolution for instances with ML2/OVN (`[ovn] dns_servers`, the host's resolvers as the fallback, and `0.0.0.0` announcing none), and `get_dhcp_dns_servers` in `neutron/common/ovn/utils.py` — https://docs.openstack.org/neutron/latest/admin/config-dns-res.html
- [V1] VirtualBox manual (nested virtualization, "Enable Nested VT-x/AMD-V"; bridged networking; promiscuous mode "Allow All") — https://www.virtualbox.org/manual/UserManual.html
- [S1] Canonical Subiquity, `subiquity/common/storage/sizes.py` (`scaled_rootfs_size`: "Use at most 100G of a large disk") — https://github.com/canonical/subiquity/blob/main/subiquity/common/storage/sizes.py
- [W1] Broadcom KB 389469, "Virtualized Intel VT-x/EPT is not supported on this platform" (names the Workstation setting "Virtualize Intel VT-x/EPT or AMD-V/RVI") — https://knowledge.broadcom.com/external/article/389469
- [H1] Heat `OS::Nova::Server` (`flavor_update_policy` RESIZE|REPLACE, default RESIZE; `user_data_update_policy` default REPLACE) — https://opendev.org/openstack/heat/src/branch/master/heat/engine/resources/openstack/nova/server.py
- [U1] Ubuntu 24.04 cloud images and their `SHA256SUMS` — https://cloud-images.ubuntu.com/noble/current/
- [U2] uv, Installation ("Request a specific version by including it in the URL"; release artifacts "can be downloaded directly from GitHub Releases") — https://docs.astral.sh/uv/getting-started/installation/; the 0.13.8 release and its `uv-x86_64-unknown-linux-gnu.tar.gz.sha256` — https://github.com/astral-sh/uv/releases/tag/0.13.8
- [U3] uv, Locking and syncing ("when `uv run` is used, the project is locked and synced before invoking the requested command"; `--frozen`: "To use the lockfile without checking if it is up-to-date"; "The `dev` group is special-cased and synced by default"; exact syncing removes unselected packages, "To retain extraneous packages, use the `--inexact` flag") — https://docs.astral.sh/uv/concepts/projects/sync/; Project configuration ("To target the system environment, set `UV_PROJECT_ENVIRONMENT` to the prefix of the Python installation", "on Debian-based systems, this is usually `/usr/local`") — https://docs.astral.sh/uv/concepts/projects/config/
- [O1] python-openstackclient, `keypair create` (`--public-key <file>`: "Filename for public key to add"; `--private-key <file>`: "Filename for private key to save") — https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/keypair.html
