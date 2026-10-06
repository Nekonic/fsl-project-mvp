#!/bin/sh
host="$1"
[ -n "$host" ] || { echo "no host given"; sleep 2; exit 1; }
addr=$(python - "$host" <<'PY'
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fsl.settings")
import django
django.setup()
from range import substrate
wanted = sys.argv[1]
try:
    for seg in substrate().describe().segments:
        if seg.id == "mgmt":
            for node in seg.nodes:
                if node.name == wanted:
                    print(node.address)
                    raise SystemExit
except SystemExit:
    pass
except Exception:
    pass
PY
)
[ -n "$addr" ] || { echo "no mgmt address for $host - the range may be down"; sleep 3; exit 1; }
exec ssh -i /data/ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=no \
  -o ConnectTimeout=10 -o ServerAliveInterval=30 "ubuntu@${addr}"
