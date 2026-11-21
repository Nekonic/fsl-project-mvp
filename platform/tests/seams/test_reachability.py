from sandbox import reachability
from sandbox.runner import Node, RangeUnavailable, Segment


class Slot:
    def __init__(self, *addresses, down=False):
        self.addresses, self.down, self.reads = addresses, down, 0

    def segments(self):
        self.reads += 1
        if self.down:
            raise RangeUnavailable("slot down")
        return (Segment(id="mgmt", name="Management",
                        nodes=tuple(Node(name, address) for name, address in self.addresses)),)


class Pool:
    def __init__(self, *slots):
        self.slots = slots

    def every_slot(self):
        return list(self.slots)


def test_every_slot_s_hosts_are_scored_but_the_platform_itself_and_a_down_slot_are_not():
    pool = Pool(Slot(("cr-kali", "172.29.0.20"), ("cr-platform", "172.29.0.2")), Slot(down=True),
                Slot(("cr-waf", "172.29.1.12")))

    assert reachability.addresses(pool, scorer="cr-platform") == {"172.29.0.20", "172.29.1.12"}


def test_the_hosts_are_read_once_per_ttl():
    clock = [0.0]
    slot = Slot(("cr-kali", "172.29.0.20"))
    hosts = reachability.ScoredHosts(slot, ttl=30, clock=lambda: clock[0])

    assert hosts.refuses("172.29.0.20") and not hosts.refuses("10.0.0.9") and not hosts.refuses("")
    clock[0] = 29
    hosts.known()
    assert slot.reads == 1
    clock[0] = 31
    hosts.known()
    assert slot.reads == 2
