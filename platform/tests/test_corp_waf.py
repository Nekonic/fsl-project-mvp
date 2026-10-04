import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORP_CONF = ROOT / "deploy/nginx/corp.conf"
RANGE_CONF = ROOT / "deploy/waf/range.conf"


def test_the_docker_corp_vhost_serves_corp_com_and_404s_internal():
    conf = CORP_CONF.read_text()
    assert "server_name corp.com;" in conf
    assert "corp-wp" in conf
    assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", conf), conf
    assert "default_server" not in conf


def test_the_cloud_waf_404s_internal_in_the_corp_server_block():
    text = RANGE_CONF.read_text()
    blocks = re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)
    corp = [b for b in blocks if "corp-wp" in b]
    assert corp, "range.conf has no corp vhost"
    for block in corp:
        assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", block), block
