def test_the_unauthenticated_option_flip_lets_anyone_self_register_as_administrator(option_flip_session):
    seen = option_flip_session
    users_can_register, default_role = seen["flips"]
    assert users_can_register == "200", f"the users_can_register flip did not complete, got {users_can_register!r}"
    assert seen["registration_open"] == "1"
    assert default_role == "200", f"the default_role flip did not complete, got {default_role!r}"
    assert seen["default_role"] == "administrator"
    assert seen["options_left"] == ("0", "subscriber")
