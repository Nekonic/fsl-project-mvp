#!/bin/sh
host="$1"
[ -n "$host" ] || { echo "no host given"; sleep 2; exit 1; }
found=$(python - "$host" "${2:-}" <<'PY'
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
import django
django.setup()
from api.models import Session
from range import substrate
wanted = sys.argv[1]
adapter = substrate()
held = Session.objects.filter(pk=int(sys.argv[2]), ended_at=None).values_list("slot", flat=True).first() if sys.argv[2].isdigit() else None
if hasattr(adapter, "in_slot"):
    if held is None and adapter.slots > 1:
        print(f"no open session {sys.argv[2] or '(none given)'}; with {adapter.slots} slots "
              f"there is no telling which slot's {wanted} to open", file=sys.stderr)
        raise SystemExit(2)
    adapter = adapter.in_slot(held or 1)
try:
    for seg in adapter.describe().segments:
        if seg.id == "mgmt":
            for node in seg.nodes:
                if node.name == wanted:
                    print(node.address, adapter.host_key_alias(node.address) or node.address)
                    raise SystemExit
except SystemExit:
    pass
except Exception:
    pass
PY
) || { sleep 3; exit 1; }
addr="${found% *}"
alias="${found#* }"
shown="${host#fsl-}"
[ -n "$addr" ] || { echo "no mgmt address for $shown - the range may be down"; sleep 3; exit 1; }
exec ssh -t -i /data/ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o HostKeyAlias="$alias" -o LogLevel=ERROR \
  -o ConnectTimeout=10 -o ServerAliveInterval=30 "ubuntu@${addr}" \
  "exec bash --rcfile <(printf '%s\\n' '. /etc/profile' '. ~/.profile' 'export TZ=Asia/Seoul' 'PS1=\${PS1//\\\\h/$shown}' '[ -r /etc/motd ] && cat /etc/motd') -i"
