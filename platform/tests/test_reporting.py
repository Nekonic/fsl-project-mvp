from range import ports

def test_the_wrapper_carries_no_option_terminator_freebsd_sh_would_run():
    assert "--" not in ports.reporting(["echo", "hi"]), (
        "the OPNsense edge's shell is FreeBSD /bin/sh, which reads the operand after "
        "'-c' as the command string, so 'sh -c -- CMD' runs '--'"
    )
