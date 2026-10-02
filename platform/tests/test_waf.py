import pathlib

from range import fabric, waf

ROOT = pathlib.Path(__file__).resolve().parents[2]

def test_the_audit_log_shipped_is_the_one_modsecurity_writes():
    configured = (ROOT / waf.MODSECURITY).read_text()

    assert waf.audit_log(configured) == "/var/log/modsecurity/audit/audit.log"

def test_rsyslog_tails_the_audit_log_as_modsecurity_and_forwards_it_by_udp():
    conf = waf.forwarding("/var/log/modsecurity/audit/audit.log", "10.31.0.195", fabric.COLLECTOR_PORT)

    assert 'File="/var/log/modsecurity/audit/audit.log"' in conf
    assert 'Tag="modsecurity"' in conf, "the collector decodes a line by its program name"
    assert 'Target="10.31.0.195"' in conf and f'Port="{fabric.COLLECTOR_PORT}"' in conf
    assert 'Protocol="udp"' in conf
    assert 'maxMessageSize="64k"' in conf, (
        "an audit record runs to several kilobytes and rsyslog cuts a line at 8k by default"
    )

def test_the_forwarding_is_written_checked_and_applied_with_sudo():
    command = waf.command()

    assert command[:2] == ["sh", "-c"]
    assert f"sudo tee {waf.CONF}" in command[2]
    assert "rsyslogd -N1" in command[2] and "systemctl restart rsyslog" in command[2]
