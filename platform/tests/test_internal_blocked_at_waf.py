import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RANGE_CONF = ROOT / "deploy" / "waf" / "range.conf"
BOARD_CONF = ROOT / "deploy" / "nginx" / "board.conf"


def _server_blocks(text):
    return re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)


def test_the_cloud_waf_404s_internal_in_every_board_server_block():
    text = RANGE_CONF.read_text(encoding="utf-8")
    for block in _server_blocks(text):
        if "board:8000" in block:
            assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", block), block


def test_the_docker_board_vhost_is_default_and_404s_internal():
    conf = BOARD_CONF.read_text(encoding="utf-8")
    assert "default_server" in conf
    assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", conf), conf
