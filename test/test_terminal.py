import requests

from conftest import PLATFORM_URL
from range import BOARD, run

def test_the_terminal_is_on_the_platform_s_port(stack_is_up):
    page = requests.get(f"{PLATFORM_URL}/terminal/", timeout=10)

    assert page.ok and "ttyd" in page.text.lower(), page.status_code

def test_a_host_in_the_range_is_refused_the_terminal(stack_is_up):
    answer = run(BOARD, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "--max-time", "5", "--noproxy", "*",
        "-H", "Host: localhost:8000",
        "http://platform:8000/terminal/",
    ])

    assert answer.stdout.strip() == "403", answer.output[-300:]
