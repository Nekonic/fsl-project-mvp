#!/bin/sh
HERE=$(cd "$(dirname "$0")" && pwd)
what=$1; shift
t=$(date +%s.%N)
case "$what" in
  reset)
    for n in "$@"; do sh "$HERE/slot.sh" reset "$n" board 2>/dev/null | tail -1 & done ;;
  reset_fast)
    for n in "$@"; do sh "$HERE/slot.sh" reset_fast "$n" board 2>/dev/null | tail -1 & done ;;
  sqlmap)
    python3 -c "
import yaml
cases = yaml.safe_load(open('$HERE/../../../redteam/cases/board.yaml'))
yaml.safe_dump([c for c in cases if c['name'] == 'board-sqli-orderby-sqlmap'], open('/opt/proto/runs/sqlmap.yaml', 'w'))"
    for n in "$@"; do
      python3 "$HERE/fire.py" "$n" /opt/proto/runs/sqlmap.yaml http://board.com "/opt/proto/runs/sqlmap-s$n.json" 2>&1 | grep -v '^total' | sed "s/^/s$n /" &
    done ;;
esac
wait
echo "$what $* wall $(awk -v a="$t" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }')s"
