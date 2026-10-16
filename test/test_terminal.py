from range import BOARD, run

def test_a_host_in_the_range_is_refused_the_terminal(stack_is_up):
    answer = run(BOARD, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "--max-time", "5", "--noproxy", "*",
        "-H", "Host: localhost:8000",
        "http://platform:8000/terminal/",
    ])

    assert answer.stdout.strip() == "403", answer.output[-300:]
