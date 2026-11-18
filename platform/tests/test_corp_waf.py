import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAF_CONF = ROOT / "deploy/waf/board.com.conf"


def test_the_cloud_waf_404s_internal_in_the_corp_server_block():
    text = WAF_CONF.read_text()
    blocks = re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)
    corp = [b for b in blocks if "corp-wp" in b]
    assert corp, "board.com.conf has no corp vhost"
    for block in corp:
        assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", block), block
