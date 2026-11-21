import pytest

from cr import errors
from testing.fakerange import BR, BR_CUSTOMERS, REFUSED_PAGE, RU, US, US_CUSTOMERS
from tests import rounds
from tests.training.attack.conftest import url
from training.attack import actions as service
from training.models import OriginBudget

pytestmark = pytest.mark.django_db

CUSTOMERS = (*US_CUSTOMERS, *BR_CUSTOMERS)


@pytest.fixture
def spent_round(make_round, learner, browser, cloud):
    found = make_round(hp={"budget": 3})
    rounds.playing(found, "attack", learner)
    browser.force_authenticate(learner)
    cloud.box.answer("cr.status=", REFUSED_PAGE)
    for _ in range(3):
        browser.post(url(found, "requests/"), {"method": "GET", "path": "/"}, format="json")
    cloud.box.answer("cr.status=", "HTTP/1.1 200 OK\r\n\r\nwelcome\ncr.status=200\n")
    return found


def test_every_attack_origin_is_spent_and_no_customer_address_ever_reaches_the_spent_set(spent_round, cloud):
    spent_at_edge = [one.text for one in cloud.edge.matching("edge spent")]

    assert not OriginBudget.objects.filter(round=spent_round, spent_at=None).exists()
    assert len(spent_at_edge) == 3
    assert not any(customer in text for text in spent_at_edge for customer in CUSTOMERS)


def test_the_edge_refill_keeps_customers_in_the_pool_and_out_of_the_spent_set(spent_round, cloud):
    service.refill_edge(spent_round)

    refilled = cloud.edge.matching("nft -f -")[-1].stdin
    pool_line, spent_line = refilled.splitlines()
    assert all(address in pool_line for address in (RU, US, BR, *CUSTOMERS))
    assert all(address in spent_line for address in (RU, US, BR))
    assert not any(customer in spent_line for customer in CUSTOMERS)


def test_customers_keep_sending_after_every_attack_origin_is_spent(spent_round, cloud):
    sent = service.send_as_customer(spent_round, US_CUSTOMERS[0], "GET", "/", headers={"User-Agent": "Mozilla/5.0"})

    customer_send = cloud.box.sent[-1]
    assert sent.status == 200 and sent.body == "welcome" and sent.action is None
    assert customer_send.argv[:3] == ["sudo", "sh", "-c"]
    assert "setpriv --reuid=cr-users" in customer_send.argv[3]
    assert f"--interface {US_CUSTOMERS[0]}" in customer_send.argv[3]
    assert f"X-Request-ID: {sent.marker}" in customer_send.argv[3]


def test_a_benign_case_fires_from_a_customer_address_after_the_spend_and_costs_no_hp(spent_round, cloud):
    before = list(OriginBudget.objects.filter(round=spent_round).values_list("left", flat=True))

    fired = service.fire_benign(spent_round, "board-normal-search-with-apostrophe", BR_CUSTOMERS[0])

    customer_send = cloud.box.sent[-1]
    assert fired.status == 200 and fired.source_ip == BR_CUSTOMERS[0]
    assert f"--interface {BR_CUSTOMERS[0]}" in customer_send.argv[3]
    assert f"X-Request-ID: {fired.marker}" in customer_send.argv[3]
    assert list(OriginBudget.objects.filter(round=spent_round).values_list("left", flat=True)) == before


def test_a_customer_send_from_an_attack_address_is_refused(spent_round):
    with pytest.raises(errors.Invalid):
        service.send_as_customer(spent_round, RU, "GET", "/")
    with pytest.raises(errors.Invalid):
        service.fire_benign(spent_round, "board-normal-search-with-apostrophe", US)


def test_the_customer_origins_never_offer_an_attack_or_the_unbound_address(attack_round):
    offered = {address for origin in service.customer_origins(attack_round) for address in origin["addresses"]}

    assert offered == set(CUSTOMERS)
