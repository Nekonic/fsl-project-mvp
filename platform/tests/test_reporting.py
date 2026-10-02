import subprocess

from range import ports

def test_the_wrapper_carries_no_option_terminator_and_a_safe_command_string():
    wrapped = ports.reporting(["echo", "hi"])

    assert wrapped[:2] == ["sh", "-c"]
    assert "--" not in wrapped, (
        "pfSense's admin shell is FreeBSD /bin/sh, which reads the operand after "
        "'-c' as the command string, so 'sh -c -- CMD' runs '--'"
    )
    assert not wrapped[2].startswith("-"), (
        "the command string is handed straight to sh -c, so if it began with a "
        "dash bash would parse it as more sh options; it passes the argv as "
        "positional parameters instead"
    )

def test_an_argument_that_looks_like_an_option_runs_as_a_command_not_an_sh_flag():
    done = subprocess.run(ports.reporting(["-ewhatever", "x"]), capture_output=True, text=True)
    ran = ports.reported(done)

    assert ran is not None, done.stderr
    assert ran.exit_code == 127, (
        f"'-ewhatever' is a command the host does not have, reported as 127, not "
        f"an option to the shell that runs it: {ran}"
    )

def test_arguments_reach_the_command_exactly_without_word_splitting_or_expansion():
    done = subprocess.run(
        ports.reporting(["printf", "%s\\n", "a b", "c;d", "$HOME"]),
        capture_output=True, text=True,
    )
    ran = ports.reported(done)

    assert ran is not None and ran.exit_code == 0
    assert ran.output == "a b\nc;d\n$HOME\n", ran.output

def test_the_wrapper_reports_the_commands_own_exit_code():
    done = subprocess.run(ports.reporting(["sh", "-c", "echo out; exit 7"]),
                          capture_output=True, text=True)
    ran = ports.reported(done)

    assert ran is not None and ran.exit_code == 7 and "out" in ran.output
