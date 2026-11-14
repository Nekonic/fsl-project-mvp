#!/bin/sh
host="$1"
shown="${host#cr-}"
log="${TERMINAL_LOG:-/data/terminal.log}"
: >> "$log" 2>/dev/null || log=/dev/null
failed() {
  [ -z "$1" ] || printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${shown:-terminal}" "$1" >> "$log" 2>/dev/null
  echo "Connection to ${shown:-the terminal} failed. Reopen the terminal in a moment."
  sleep 3
  exit 1
}
[ -n "$host" ] || failed "no host given"
case "${2:-}" in
  ''|*[!0-9]*) ;;
  *) [ -z "${TERMINAL_KEEP:-}" ] || [ -n "${TMUX:-}" ] || exec tmux -f /app/tmux.conf new-session -A -s "${shown}-$2" "$0" "$host" "$2" ;;
esac
found=$(python - "$host" "${2:-}" 2>>"$log" <<'PY'
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cr.settings")
import django
django.setup()
from api.models import Session
from range import substrate
wanted = sys.argv[1]
adapter = substrate()
held = Session.objects.filter(pk=int(sys.argv[2]), ended_at=None).values_list("slot", flat=True).first() if sys.argv[2].isdigit() else None
if held is None and adapter.slots > 1:
    print(f"no open session {sys.argv[2] or '(none given)'}; with {adapter.slots} slots "
          f"there is no telling which slot's {wanted} to open", file=sys.stderr)
    raise SystemExit(2)
print(*adapter.in_slot(held or 1).terminal(wanted))
PY
) || failed "lookup of ${2:+session $2 }$host refused"
set -- $found
addr="$1"
alias="$2"
container="$3"
[ -n "$addr" ] && [ -n "$container" ] || failed "no range host address or container for $host"
options="-t -i /data/ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o HostKeyAlias=$alias -o LogLevel=ERROR -o ConnectTimeout=10 -o ServerAliveInterval=30"
ssh $options "ubuntu@${addr}" "sudo docker exec -it -e TERM=xterm-256color -e TZ=Asia/Seoul -w /root $container bash -l" 2>>"$log"
status=$?
[ "$status" -ne 255 ] || failed "ssh to $host at $addr ended with 255"
exit "$status"
