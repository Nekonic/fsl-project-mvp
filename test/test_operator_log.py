def test_commands_typed_in_the_attacker_s_shell_reach_the_round_s_feed_in_order(terminal_round):
    commands = terminal_round["commands"]

    assert "nmap --version" in commands and "echo after" in commands, commands
    assert commands.index("nmap --version") < commands.index("echo after"), commands
