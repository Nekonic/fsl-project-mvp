#!/bin/sh
host="$1"
side="$2"
round="${3:-}"
shown="${host#cr-}"
app="$(dirname "$0")"
log="${TERMINAL_LOG:-/data/terminal.log}"
: >> "$log" 2>/dev/null || log=/dev/null
failed() {
  [ -z "$1" ] || printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${shown:-terminal}" "$1" >> "$log" 2>/dev/null
  echo "Connection to ${shown:-the terminal} failed. Reopen the terminal in a moment."
  sleep 3
  exit 1
}
[ -n "$host" ] || failed "no host given"
case "$side" in
  attack|defence|ids) ;;
  *) failed "no player side given for $host" ;;
esac
case "$round" in
  ''|*[!0-9]*) failed "no round given for the $side player's $host" ;;
esac
[ -z "${TERMINAL_KEEP:-}" ] || [ -n "${TMUX:-}" ] || ! command -v tmux >/dev/null 2>&1 \
  || exec tmux -f "$app/tmux.conf" new-session -A -s "${side}-${round}" "$0" "$host" "$side" "$round"
found=$(python "$app/manage.py" terminal_shell "$side" "$round" 2>>"$log") \
  || failed "round $round refused the $side player's terminal on $host"
set -- $found
addr="$1"
alias="$2"
account="$3"
[ -n "$addr" ] && [ -n "$alias" ] || failed "no management address for the $side player's $host"
case "$account" in
  ''|*[!a-z0-9_-]*) failed "no account for the $side player's $host" ;;
esac
options="-t -i /data/ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o HostKeyAlias=$alias -o LogLevel=ERROR -o ConnectTimeout=10 -o ServerAliveInterval=30"
recheck="${TERMINAL_RECHECK:-15}"
exec 3<&0
ssh $options "${CR_OPENSTACK_SSH_USER:-ubuntu}@${addr}" "sudo -i -u $account env TERM=xterm-256color TZ=KST-9 bash -l" <&3 2>>"$log" &
shell=$!
exec 3<&-
(
  while sleep "$recheck"; do
    python "$app/manage.py" terminal_shell "$side" "$round" >/dev/null 2>>"$log" && continue
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$shown" "round $round no longer gives the $side player a terminal; closing it" >> "$log" 2>/dev/null
    kill "$shell" 2>/dev/null
    exit 3
  done
) >/dev/null 2>&1 &
watcher=$!
wait "$shell"
status=$?
kill "$watcher" 2>/dev/null
wait "$watcher"
[ "$?" -ne 3 ] || exit 0
[ "$status" -ne 255 ] || failed "ssh to $host at $addr ended with 255"
exit "$status"
