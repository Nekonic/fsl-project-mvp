from __future__ import annotations

import re

MODSECURITY = "deploy/waf/modsecurity.conf"
TAG = "modsecurity"

def conf(tag: str) -> str:
    return f"/etc/rsyslog.d/60-fsl-{tag}.conf"

CONF = conf(TAG)

def audit_log(configured: str) -> str:
    return re.search(r"^SecAuditLog\s+(\S+)", configured, re.MULTILINE)[1]

def forwarding(path: str, collector: str, port: int, tag: str = TAG) -> str:
    return (
        'global(maxMessageSize="64k")\n'
        'module(load="imfile")\n'
        f'input(type="imfile" File="{path}" Tag="{tag}" Facility="local2" '
        f'Severity="info" ruleset="fsl-{tag}")\n'
        f'ruleset(name="fsl-{tag}") {{\n'
        f'    action(type="omfwd" Target="{collector}" Port="{port}" Protocol="udp" '
        'Template="RSYSLOG_SyslogProtocol23Format")\n'
        '}\n'
    )

def command(tag: str = TAG) -> list[str]:
    return ["sh", "-c", f"sudo tee {conf(tag)} >/dev/null && sudo rsyslogd -N1 && "
                        f"sudo systemctl restart rsyslog"]
