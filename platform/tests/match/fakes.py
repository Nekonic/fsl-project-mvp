from __future__ import annotations

from dataclasses import dataclass, field

from range.networks import Plan as FabricPlan
from range.pool import Plan
from range.wiring import Wiring
from tests.attack.fakes import FakeRange as AttackRange
from tests.defence import fakerange
from tests.referee import targets
from testing.fakes import FakeRunner

ASSIGNED = {1: "board", 2: "corp", 3: "board"}
RECORDS = "cr.records=\n\n=cr.records\n"
POST_PAGE = ("HTTP/1.1 200 OK\r\nSet-Cookie: csrftoken=abc123\r\n\r\n"
             '<input name="csrfmiddlewaretoken" value="tok456">\nhttp_code=200\n')


@dataclass
class FakeSlot(AttackRange):
    slot: int = 1
    defence: fakerange.FakeRange = field(default_factory=fakerange.FakeRange)
    target: FakeRunner = field(default_factory=lambda: targets.board_runner(targets.TRUTH))
    resets: int = 0
    ensured: list[str] = field(default_factory=list)
    configured: int = 0

    def __post_init__(self):
        super().__post_init__()
        self.box.answer("cr.records=", RECORDS)
        self.box.answer("board.com/posts/1/", POST_PAGE)
        self.defence.runner("sensor").rules = 'alert http any any -> any any (msg:"baseline"; sid:9000001; rev:1;)\n'

    @property
    def wargame(self) -> str:
        return ASSIGNED.get(self.slot, "")

    def runner(self, role: str, segment_id: str = ""):
        if role == "edge":
            return self.edge
        if role in ("attacker", "proxy"):
            return self.box
        if role == "board":
            return self.target
        return self.defence.runner(role)

    def node_runner(self, role: str):
        return self.defence.node_runner(role)

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


HELD: dict[str, FakeCloud] = {}


def connect(options, declared) -> FakeCloud:
    return HELD["cloud"]
