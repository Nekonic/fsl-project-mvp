from suppress import MARKER, discard, find, restore, silence

RULES = '''# FSL MVP baseline rules.

alert http any any -> any any (msg:"FSL SQLi attempt - URI"; sid:9000001; rev:1;)

alert http any any -> any any (msg:"FSL XSS attempt"; sid:9000003; rev:1;)
'''

def test_silencing_comments_the_rule_and_says_when_it_returns():
    out = silence(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert f'{MARKER} until 2026-09-20T13:00:00Z' in out
    assert '#alert http any any -> any any (msg:"FSL SQLi attempt - URI"' in out
    assert 'sid:9000001' in out
    assert find(out, 9000003) is not None

def test_restoring_puts_the_line_back_byte_for_byte():
    original = find(RULES, 9000001)
    silenced = silence(RULES, 9000001, "2026-09-20T13:00:00Z")

    assert restore(silenced, 9000001, original) == RULES

def test_only_the_named_rule_is_touched_when_two_are_silenced():
    first = find(RULES, 9000001)
    both = silence(silence(RULES, 9000001, "t1"), 9000003, "t2")

    back = restore(both, 9000001, first)

    assert find(back, 9000001) is not None
    assert find(back, 9000003) is None

RIVAL = 'alert http any any -> any any (msg:"FSL replaces sid:100"; sid:1000; rev:1;)'
RULE = 'alert http any any -> any any (msg:"FSL original"; sid:100; rev:1;)'

def test_a_msg_that_names_a_sid_does_not_make_its_rule_that_sid():
    assert find(f"{RIVAL}\n{RULE}\n", 100) == RULE
    assert silence(f"{RIVAL}\n{RULE}\n", 100, "t") == f"{RIVAL}\n{MARKER} until t\n#{RULE}\n"
    both = f"{MARKER} until t1\n#{RIVAL}\n{MARKER} until t2\n#{RULE}\n"
    assert restore(both, 100, RULE) == f"{MARKER} until t1\n#{RIVAL}\n{RULE}\n"

def test_silencing_and_restoring_edit_the_rule_not_a_commented_copy_of_it():
    assert silence(f"#{RULE}\n{RULE}\n", 100, "t") == f"#{RULE}\n{MARKER} until t\n#{RULE}\n"
    assert restore(f"#{RULE}\n{MARKER} until t\n#{RULE}\n", 100, RULE) == f"#{RULE}\n{RULE}\n"

REPLACEMENT = 'alert http any any -> any any (msg:"FSL original, reworded"; sid:100; rev:1;)'

def test_discarding_drops_the_marker_and_the_silenced_copy_and_nothing_else():
    replaced = f"#{RULE}\n{MARKER} until t\n#{RULE}\n{REPLACEMENT}\n"

    assert discard(replaced, 100, RULE) == f"#{RULE}\n{REPLACEMENT}\n"
