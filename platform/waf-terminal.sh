#!/bin/sh
session="$1"
case "$session" in
  ""|*[!0-9]*) echo "no session given"; sleep 2; exit 1 ;;
esac
rc=$(cat <<'RC'
[ -r ~/.bashrc ] && . ~/.bashrc
PS1='\u@waf:\w\$ '
RC
)
docker exec -it "fsl-${session}-waf-1" bash -c 'exec bash --rcfile <(printf "%s\n" "$0") -i' "$rc" || { echo "session ${session} has no running WAF"; sleep 3; exit 1; }
