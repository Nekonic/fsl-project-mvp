from datetime import datetime, timedelta, timezone

from domain.ledger import cost, debit, next_origin, opened, spend
from domain.types import Charge, HpRule

T0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
RULE = HpRule(budget=10, per_request=1, refused_x=3, burst_per_s=2, burst_x=2)
ORIGINS = [("o1", "203.0.113.1", "first"), ("o2", "203.0.113.2", "second")]


def charge(seconds, ip="203.0.113.1", refused=False, marker=None, synchronous=False):
    return Charge(origin_ip=ip, at=T0 + timedelta(seconds=seconds), refused=refused, marker=marker,
                  synchronous=synchronous)


def left(state, ip="203.0.113.1"):
    return next(o.left for o in state.origins if o.ip == ip)


def test_each_origin_starts_at_the_budget():
    state = opened(ORIGINS, RULE)

    assert [(o.budget, o.left, o.spent) for o in state.origins] == [(10, 10, False), (10, 10, False)]
    assert state.origins_left == 2


def test_each_request_costs_per_request():
    state, spent = debit(opened(ORIGINS, RULE), [charge(0), charge(1)], RULE)

    assert left(state) == 8
    assert spent == ()


def test_refusals_by_400_and_403_cost_refused_x():
    assert RULE.refuses(400) and RULE.refuses(403) and not RULE.refuses(200) and not RULE.refuses(404)

    state, _ = debit(opened(ORIGINS, RULE), [charge(0, refused=RULE.refuses(403)),
                                              charge(1, refused=RULE.refuses(400))], RULE)

    assert left(state) == 10 - 3 - 3


def test_requests_beyond_the_burst_within_one_second_cost_burst_x():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0.1), charge(0.2), charge(0.3), charge(0.9)], RULE)

    assert left(state) == 10 - 1 - 1 - 2 - 2


def test_the_burst_count_carries_across_debits_in_the_same_second():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0.1), charge(0.2)], RULE)
    state, _ = debit(state, [charge(0.5)], RULE)

    assert left(state) == 10 - 1 - 1 - 2


def test_the_multipliers_combine_by_multiplication():
    assert cost(RULE, refused=True, in_burst=True) == 1 * 3 * 2


def test_an_origin_is_spent_at_zero_and_spends_are_reported_in_order():
    rule = HpRule(budget=2, per_request=1, refused_x=3, burst_per_s=100, burst_x=2)
    state, spent = debit(
        opened(ORIGINS, rule),
        [charge(5, ip="203.0.113.1"), charge(1, ip="203.0.113.2", refused=True), charge(6, ip="203.0.113.1")],
        rule,
    )

    assert [o.ip for o in spent] == ["203.0.113.2", "203.0.113.1"]
    assert spent[0].spent_at == T0 + timedelta(seconds=1)
    assert state.origins_left == 0
    assert state.spent_ips == ("203.0.113.1", "203.0.113.2")


def test_a_spent_origin_is_not_charged_again():
    rule = HpRule(budget=1, per_request=1, refused_x=1, burst_per_s=100, burst_x=1)
    state, first = debit(opened(ORIGINS, rule), [charge(0)], rule)
    state, again = debit(state, [charge(1)], rule)

    assert [o.ip for o in first] == ["203.0.113.1"]
    assert again == ()
    assert left(state) == 0


def test_an_access_event_for_a_request_already_charged_by_the_api_is_skipped():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0, marker="a1", synchronous=True)], RULE)
    state, _ = debit(state, [charge(0.5, marker="a1"), charge(3, marker="window-7"), charge(4, marker="window-7")], RULE)

    assert left(state) == 10 - 1 - 1 - 1



def test_an_access_event_in_the_same_batch_as_its_api_charge_is_skipped_whatever_its_time():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0.5, marker="a1", synchronous=True), charge(0, marker="a1")], RULE)

    assert left(state) == 10 - 1

def test_customers_and_unknown_addresses_are_never_charged():
    state, spent = debit(opened(ORIGINS, RULE), [charge(0, ip="198.51.100.9", refused=True)], RULE)

    assert [o.left for o in state.origins] == [10, 10]
    assert spent == ()


def test_giving_up_an_origin_spends_it_and_the_next_is_the_first_unspent():
    state = opened(ORIGINS, RULE)
    assert next_origin(state).ip == "203.0.113.1"

    state, spent = spend(state, "203.0.113.1", T0)

    assert spent.ip == "203.0.113.1"
    assert next_origin(state).ip == "203.0.113.2"
    assert spend(state, "203.0.113.1", T0)[1] is None

    state, _ = spend(state, "203.0.113.2", T0)
    assert next_origin(state) is None


def test_an_api_charge_excuses_one_access_event_and_every_other_event_carrying_its_marker_is_charged():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0, marker="a1", synchronous=True)], RULE)
    state, _ = debit(state, [charge(0.5, marker="a1"), charge(3, marker="a1"), charge(5, marker="a1")], RULE)

    assert left(state) == 10 - 1 - 1 - 1
    assert state.charged_markers == frozenset()


def test_an_excused_marker_stays_spent_across_batches():
    state, _ = debit(opened(ORIGINS, RULE), [charge(0, marker="a1", synchronous=True)], RULE)
    state, _ = debit(state, [charge(0.5, marker="a1")], RULE)
    state, _ = debit(state, [charge(3, marker="a1")], RULE)

    assert left(state) == 10 - 1 - 1
