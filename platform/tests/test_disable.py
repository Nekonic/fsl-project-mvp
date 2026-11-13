from disable import MARKER, comment_out, discard, find, uncomment

RULES = '''# Baseline rules.

alert http any any -> any any (msg:"SQLi attempt - URI"; sid:9000001; rev:1;)

alert http any any -> any any (msg:"XSS attempt"; sid:9000003; rev:1;)
'''

def test_disabling_comments_the_rule_out_and_says_when_it_returns():
    out = comment_out(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert f'{MARKER} until 2026-09-20T13:00:00Z' in out
    assert '#alert http any any -> any any (msg:"SQLi attempt - URI"' in out
    assert 'sid:9000001' in out
    assert find(out, 9000003) is not None

def test_enabling_puts_the_line_back_byte_for_byte():
    original = find(RULES, 9000001)
    disabled = comment_out(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert uncomment(disabled, 9000001, original) == RULES

def test_only_the_named_rule_is_touched_when_two_are_disabled():
    first = find(RULES, 9000001)
    both = comment_out(comment_out(RULES, 9000001, "t1"), 9000003, "t2")

    back = uncomment(both, 9000001, first)

    assert find(back, 9000001) is not None
    assert find(back, 9000003) is None

RIVAL = 'alert http any any -> any any (msg:"replaces sid:100"; sid:1000; rev:1;)'
RULE = 'alert http any any -> any any (msg:"original"; sid:100; rev:1;)'

def test_a_msg_that_names_a_sid_does_not_make_its_rule_that_sid():
    assert find(f"{RIVAL}\n{RULE}\n", 100) == RULE
    assert comment_out(f"{RIVAL}\n{RULE}\n", 100, "t") == f"{RIVAL}\n{MARKER} until t\n#{RULE}\n"
    both = f"{MARKER} until t1\n#{RIVAL}\n{MARKER} until t2\n#{RULE}\n"
    assert uncomment(both, 100, RULE) == f"{MARKER} until t1\n#{RIVAL}\n{RULE}\n"

def test_disabling_and_enabling_edit_the_rule_not_a_commented_copy_of_it():
    assert comment_out(f"#{RULE}\n{RULE}\n", 100, "t") == f"#{RULE}\n{MARKER} until t\n#{RULE}\n"
    assert uncomment(f"#{RULE}\n{MARKER} until t\n#{RULE}\n", 100, RULE) == f"#{RULE}\n{RULE}\n"

REPLACEMENT = 'alert http any any -> any any (msg:"original, reworded"; sid:100; rev:1;)'

def test_discarding_drops_the_marker_and_the_commented_copy_and_nothing_else():
    replaced = f"#{RULE}\n{MARKER} until t\n#{RULE}\n{REPLACEMENT}\n"

    assert discard(replaced, 100, RULE) == f"#{RULE}\n{REPLACEMENT}\n"

def test_a_rule_disabled_before_the_marker_was_renamed_can_still_be_enabled():
    for old in ("# cr-disabled", "# cr-suppressed"):
        disabled = f"{old} until t\n#{RULE}\n"

        assert uncomment(disabled, 100, RULE) == f"{RULE}\n"
        assert discard(disabled + f"{REPLACEMENT}\n", 100, RULE) == f"{REPLACEMENT}\n"

def test_a_rule_is_disabled_under_the_new_marker():
    assert comment_out(f"{RULE}\n", 100, "t") == f"# cr-disabled until t\n#{RULE}\n"
