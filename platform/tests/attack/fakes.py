from __future__ import annotations

from dataclasses import dataclass, field

from range.runner import Node, Segment, Shape
from testing.fakes import FakeRunner

KALI = "cr-kali"
KALI_MANAGEMENT = "172.29.0.20"
UNBOUND = "172.29.0.20"
RU, US, BR = "5.188.10.10", "73.0.0.10", "177.54.144.10"
US_CUSTOMERS = ("73.0.0.11", "73.0.0.12")
BR_CUSTOMERS = ("177.54.144.11",)
OK_PAGE = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nServer: nginx\r\n\r\n<p>hello</p>\ncr.status=200\n"
REFUSED_PAGE = "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\nrefused\ncr.status=403\n"


def segment(segment_id: str, label: str, attack: str, customers: tuple[str, ...]) -> Segment:
    nodes = tuple(Node(KALI, address) for address in customers) + (Node(KALI, attack),)
    return Segment(id=segment_id, name=label, origin=label, subnet=f"{attack}/24", network=f"net-{segment_id}",
                   gateway=attack.rsplit(".", 1)[0] + ".1", nodes=nodes + (Node("cr-edge", attack[:-2] + "1"),))


@dataclass
class FakeRange:
    box: FakeRunner = field(default_factory=FakeRunner)
    edge: FakeRunner = field(default_factory=FakeRunner)
    launched: list[str] = field(default_factory=list)
    segments_given: tuple[Segment, ...] = field(default_factory=lambda: (
        segment("ru", "Russia", RU, ()),
        segment("us", "United States", US, US_CUSTOMERS),
        segment("br", "Brazil", BR, BR_CUSTOMERS),
    ))

    def __post_init__(self):
        self.box.answer("ip -o route get", f"10.30.0.1 via 121.134.88.41 dev eth0 src {UNBOUND} uid 0\n")
        self.box.answer("cr.status=", OK_PAGE)
        self.box.answer("http_code=", "http_code=200\n")

    def describe(self) -> Shape:
        return Shape(segments=self.segments_given, sensors=())

    def segments(self):
        return self.segments_given

    def runner(self, role: str, segment_id: str = "") -> FakeRunner:
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
