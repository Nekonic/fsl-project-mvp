from __future__ import annotations

import re

MODSECURITY = "deploy/waf/modsecurity.conf"
CONF = "/etc/rsyslog.d/60-fsl-modsecurity.conf"

def audit_log(configured: str) -> str:
    return re.search(r"^SecAuditLog\s+(\S+)", configured, re.MULTILINE)[1]

def forwarding(audit: str, collector: str, port: int) -> str:
    return (
        'global(maxMessageSize="64k")\n'
        'module(load="imfile")\n'
        f'input(type="imfile" File="{audit}" Tag="modsecurity" Facility="local2" '
        'Severity="info" ruleset="fsl-modsecurity")\n'
        'ruleset(name="fsl-modsecurity") {\n'
        f'    action(type="omfwd" Target="{collector}" Port="{port}" Protocol="udp" '
        'Template="RSYSLOG_SyslogProtocol23Format")\n'
        '}\n'
    )

def command() -> list[str]:
    return ["sh", "-c", f"sudo tee {CONF} >/dev/null && sudo rsyslogd -N1 && "
                        f"sudo systemctl restart rsyslog"]
