from __future__ import annotations

from dataclasses import dataclass, field

from sandbox.fabric import Plan as FabricPlan
from sandbox.pool import Plan
from sandbox.runner import Node, Segment, Shape
from sandbox.wiring import Wiring
from testing.fakes import BOARD_TRUTH, FakeRunner, Gateway, Sensor, SensorNode, board_runner

KALI = "cr-kali"
CUSTOMERS = "cr-customers"
KALI_MANAGEMENT = "172.29.0.20"
WAF_MANAGEMENT = "172.29.0.30"
SENSOR_MANAGEMENT = "172.29.0.40"
RU, US, BR = "5.188.10.10", "73.0.0.10", "177.54.144.10"
US_CUSTOMERS = ("73.0.0.11", "73.0.0.12")
BR_CUSTOMERS = ("177.54.144.11",)
OK_PAGE = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nServer: nginx\r\n\r\n<p>hello</p>\ncr.status=200\n"
REFUSED_PAGE = "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\nrefused\ncr.status=403\n"
ASSIGNED = {1: "board", 2: "corp", 3: "board"}
RECORDS = "cr.records=\n\n=cr.records\n"
POST_PAGE = ("HTTP/1.1 200 OK\r\nSet-Cookie: csrftoken=abc123\r\n\r\n"
             '<input name="csrfmiddlewaretoken" value="tok456">\nhttp_code=200\n')
SENSOR_BASELINE = 'alert http any any -> any any (msg:"baseline"; sid:9000001; rev:1;)\n'


def segment(segment_id: str, label: str, attack: str, customers: tuple[str, ...]) -> Segment:
    nodes = tuple(Node(CUSTOMERS, address) for address in customers) + (Node(KALI, attack),)
    return Segment(id=segment_id, name=label, origin=label, subnet=f"{attack}/24", network=f"net-{segment_id}",
                   gateway=attack.rsplit(".", 1)[0] + ".1", nodes=nodes + (Node("cr-edge", attack[:-2] + "1"),))


@dataclass
class DefenceRange:
    sensors: dict[str, Sensor] = field(default_factory=dict)
    nodes: dict[str, SensorNode] = field(default_factory=dict)
    gateway: Gateway = field(default_factory=Gateway)
    slots: list[int] = field(default_factory=list)

    def runner(self, role: str, segment_id: str = ""):
        if role == "gateway":
            return self.gateway
        return self.sensors.setdefault(role, Sensor())

    def node_runner(self, role: str):
        return self.nodes.setdefault(role, SensorNode(sensor=self.sensors.setdefault(role, Sensor())))

    def address(self, role: str) -> str:
        return {"gateway": WAF_MANAGEMENT, "sensor": SENSOR_MANAGEMENT}.get(role, "")

    def in_slot(self, number: int) -> "DefenceRange":
        self.slots.append(number)
        return self


@dataclass
class AttackRange:
    box: FakeRunner = field(default_factory=FakeRunner)
    edge: FakeRunner = field(default_factory=FakeRunner)
    customers: FakeRunner = field(default_factory=FakeRunner)
    launched: list[str] = field(default_factory=list)
    segments_given: tuple[Segment, ...] = field(default_factory=lambda: (
        segment("ru", "Russia", RU, ()),
        segment("us", "United States", US, US_CUSTOMERS),
        segment("br", "Brazil", BR, BR_CUSTOMERS),
    ))

    def __post_init__(self):
        for runner in (self.box, self.customers):
            runner.answer("cr.status=", OK_PAGE)
            runner.answer("http_code=", "http_code=200\n")

    def describe(self) -> Shape:
        return Shape(segments=self.segments_given, sensors=())

    def segments(self):
        return self.segments_given

    def runner(self, role: str, segment_id: str = "") -> FakeRunner:
        if role == "customers":
            return self.customers
        return self.edge if role == "edge" else self.box

    def node_runner(self, role: str) -> FakeRunner:
        return self.runner(role)

    def launcher(self, segment_id: str):
        self.launched.append(segment_id)

        def launch(image: str, argv: list[str], timeout: float = 600.0):
            return self.box(argv, timeout=timeout)

        return launch

    def address(self, role: str) -> str:
        return KALI_MANAGEMENT

    def worn(self) -> list[str]:
        return [one.argv[-1] for one in self.box.matching("set-origin")]


@dataclass
class FakeSlot(AttackRange):
    slot: int = 1
    defence: DefenceRange = field(default_factory=DefenceRange)
    target: FakeRunner = field(default_factory=lambda: board_runner(BOARD_TRUTH))
    resets: int = 0
    ensured: list[str] = field(default_factory=list)
    configured: int = 0

    def __post_init__(self):
        super().__post_init__()
        self.customers.answer("cr.records=", RECORDS)
        for runner in (self.box, self.customers):
            runner.answer("board.com/posts/1/", POST_PAGE)
        self.defence.runner("sensor").rules = SENSOR_BASELINE

    @property
    def wargame(self) -> str:
        return ASSIGNED.get(self.slot, "")

    def runner(self, role: str, segment_id: str = ""):
        if role == "edge":
            return self.edge
        if role == "customers":
            return self.customers
        if role in ("attacker", "proxy"):
            return self.box
        if role == "board":
            return self.target
        return self.defence.runner(role)

    def node_runner(self, role: str):
        return self.defence.node_runner(role)

    def address(self, role: str) -> str:
        return self.defence.address(role) or super().address(role)

    def reset_slot(self):
        self.resets += 1
        return [(f"cr-slot-{self.slot}", f"stack-{self.slot}-{self.resets}")]

    def ensure_slot(self, renew: bool = True, wargame: str = ""):
        self.ensured.append(wargame)
        return Plan(standing=((f"cr-slot-{self.slot}-kali", "server", "ACTIVE"),), stack_id=f"fresh-{self.slot}")

    def configure_slot(self):
        self.configured += 1
        return []

    def teardown_slot(self):
        return [("stack", f"stack-{self.slot}")]

    def wiring(self):
        return Wiring()


@dataclass
class FakeCloud:
    slots: int = 2
    held: dict[int, FakeSlot] = field(default_factory=dict)
    fabric: FabricPlan = field(default_factory=lambda: FabricPlan(present=("cr-attack", "cr-dmz")))
    leftovers: list[tuple[str, str]] = field(default_factory=list)
    fabric_removed: bool = False

    def in_slot(self, number: int) -> FakeSlot:
        return self.held.setdefault(number, FakeSlot(slot=number))

    def ensure_fabric(self) -> FabricPlan:
        return self.fabric

    def teardown_fabric(self):
        self.fabric_removed = True
        return [("network", "cr-attack"), ("network", "cr-dmz")]

    def clean_leftovers(self):
        return list(self.leftovers)

    def plan_slots(self) -> list[Plan]:
        return [Plan(slot=number, wargame=ASSIGNED.get(number, ""), standing=(
            (f"cr-slot-{number}-kali", f"server-{number}", "ACTIVE"),)) for number in range(1, self.slots + 1)]


HELD: dict[str, object] = {}


def connect(options, declared):
    return HELD["range"]
