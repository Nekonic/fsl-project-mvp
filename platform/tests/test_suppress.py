"""Silencing a rule and putting it back, with nothing running."""

import pytest

from suppress import MARKER, find, restore, silence

RULES = '''# FSL MVP baseline rules.

alert http any any -> any any (msg:"FSL SQLi attempt - URI"; sid:9000001; rev:1;)

alert http any any -> any any (msg:"FSL XSS attempt"; sid:9000003; rev:1;)
'''


def test_the_rule_carrying_a_sid_is_found():
    assert 'sid:9000001' in find(RULES, 9000001)


def test_a_sid_inside_a_comment_is_not_a_rule():
    commented = RULES.replace("alert http any any -> any any (msg:\"FSL XSS", "#alert http any any -> any any (msg:\"FSL XSS")

    assert find(commented, 9000003) is None


def test_a_sid_that_is_not_there_is_not_invented():
    assert find(RULES, 9999999) is None


def test_silencing_comments_the_rule_and_says_when_it_returns():
    out = silence(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert f'{MARKER} until 2026-09-20T13:00:00Z' in out
    assert '#alert http any any -> any any (msg:"FSL SQLi attempt - URI"' in out
    # Deleting it would leave a rule file nobody can reason about.
    assert 'sid:9000001' in out
    # Everything else is untouched.
    assert find(out, 9000003) is not None


def test_silencing_a_rule_that_is_not_there_is_refused():
    with pytest.raises(KeyError):
        silence(RULES, 9999999, "2026-09-20T13:00:00Z")


def test_restoring_puts_the_line_back_byte_for_byte():
    original = find(RULES, 9000001)
    silenced = silence(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert restore(silenced, 9000001, original) == RULES


def test_restoring_something_already_back_is_refused():
    original = find(RULES, 9000001)

    with pytest.raises(KeyError):
        restore(RULES, 9000001, original)


def test_only_the_named_rule_is_touched_when_two_are_silenced():
    first = find(RULES, 9000001)
    both = silence(silence(RULES, 9000001, "t1"), 9000003, "t2")

    back = restore(both, 9000001, first)

    assert find(back, 9000001) is not None
    assert find(back, 9000003) is None
