import re
from pathlib import Path

import pytest

WAF_CONF = Path(__file__).resolve().parents[2] / "deploy/roles/waf/sites.conf"
SERVERS = re.findall(r"^server\s*\{.*?^\}", WAF_CONF.read_text(), flags=re.DOTALL | re.MULTILINE)
INTERNAL_ANSWER = {
    "board": r"location\s+/internal/\s*\{\s*proxy_pass\s+http://board:8000/not-found/;",
    "corp-wp": r"location\s+/internal/\s*\{\s*return\s+404;",
}


def upstream(server):
    return re.search(r"proxy_pass\s+https?://([\w-]+)", server)[1]


@pytest.mark.parametrize("server", SERVERS, ids=lambda server: re.search(r"server_name\s+(\S+);", server)[1])
def test_every_server_block_answers_internal_with_its_site_s_404(server):
    assert upstream(server) in INTERNAL_ANSWER, "a server block with no /internal/ rule"
    assert re.search(INTERNAL_ANSWER[upstream(server)], server), server


def test_the_waf_config_holds_a_board_and_a_corp_server_block():
    assert {upstream(server) for server in SERVERS} >= {"board", "corp-wp"}
