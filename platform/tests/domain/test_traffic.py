from domain.traffic import allocated, busiest_per_minute, limit_floor

BOARD_ORIGINS = {"kr": 70, "jp": 6, "us": 8, "cn": 3, "vn": 3, "tw": 3, "hk": 3, "br": 2, "de": 1, "gb": 1}


def test_customers_are_shared_out_by_origin_weight_and_the_largest_remainders_take_the_rest():
    homes = allocated(BOARD_ORIGINS, 12)

    assert len(homes) == 12
    assert homes.count("kr") == 9 and homes.count("us") == 1 and homes.count("jp") == 1


def test_the_busiest_origin_sends_its_share_of_the_customers_rate():
    declared = {"users": 12, "rate": 1.0, "origins": BOARD_ORIGINS}

    assert busiest_per_minute(declared) == 45.0


def test_the_floor_is_twice_the_busiest_origin_s_rate_in_whole_requests_per_minute():
    declared = {"users": 3, "rate": 0.5, "origins": {"kr": 2, "us": 1}}

    assert limit_floor(declared) == 40
    assert limit_floor({**declared, "rate": None}) == 80, "a traffic file with no rate runs at one request a second"


def test_traffic_with_no_customers_sets_no_floor():
    assert limit_floor({"users": 0, "origins": {"kr": 1}}) == 0
    assert limit_floor({"users": 4, "origins": {}}) == 0
