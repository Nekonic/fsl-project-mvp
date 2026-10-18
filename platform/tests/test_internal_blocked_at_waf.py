import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAF_CONF = ROOT / "deploy" / "waf" / "board.com.conf"
BOARD_CONF = ROOT / "deploy" / "nginx" / "board.conf"

ANSWERED_BY_THE_BOARDS_OWN_404 = r"location\s+/internal/\s*\{\s*proxy_pass\s+(?:http://board:8000|\$board_upstream)/not-found/;"


def _server_blocks(text):
    return re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)


def test_the_cloud_waf_answers_internal_with_the_boards_own_404_in_every_board_server_block():
    text = WAF_CONF.read_text(encoding="utf-8")
    for block in _server_blocks(text):
        if "board:8000" in block:
            assert re.search(ANSWERED_BY_THE_BOARDS_OWN_404, block), block


def test_the_docker_board_vhost_is_default_and_answers_internal_with_the_boards_own_404():
    conf = BOARD_CONF.read_text(encoding="utf-8")
    assert "default_server" in conf
    assert re.search(ANSWERED_BY_THE_BOARDS_OWN_404, conf), conf
    assert "return 404" not in conf
