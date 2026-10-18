#!/bin/sh
session="$1"
log="${TERMINAL_LOG:-/data/terminal.log}"
: >> "$log" 2>/dev/null || log=/dev/null
failed() {
  printf '%s waf %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$log" 2>/dev/null
  echo "Connection to waf failed. Reopen the terminal in a moment."
  sleep 3
  exit 1
}
case "$session" in
  ""|*[!0-9]*) failed "no session given" ;;
esac
container="fsl-${session}-waf-1"
[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>>"$log")" = true ] || failed "$container is not running"
rc=$(cat <<'RC'
[ -r ~/.bashrc ] && . ~/.bashrc
export TZ=Asia/Seoul
PS1='\u@waf:\w\$ '
RC
)
docker exec -it "$container" bash -c 'exec bash --rcfile <(printf "%s\n" "$0") -i' "$rc" 2>>"$log"
