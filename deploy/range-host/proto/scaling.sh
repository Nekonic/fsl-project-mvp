#!/bin/sh
HERE=$(cd "$(dirname "$0")" && pwd)
sample() {
  while [ ! -f "$1.stop" ]; do
    sh "$HERE/measure.sh" memory | grep -E "^all|^host" | tr "\n" " "; echo
    sleep 3
  done > "$1"
}
lowest() { awk '{ for (i = 1; i <= NF; i++) if ($i == "available") { v = $(i+1); if (min == "" || v + 0 < min + 0) min = v } } END { print "min available " min " MiB" }' "$1"; }
for kind in "$@"; do
  for set in "1" "1 2" "1 2 3" "1 2 3 4"; do
    log=/opt/proto/runs/mem-$kind-$(echo "$set" | tr -d " ")
    rm -f "$log.stop"; sample "$log" & s=$!
    sh "$HERE/parallel.sh" "$kind" $set
    touch "$log.stop"; wait "$s"
    [ "$kind" = sqlmap ] && sh "$HERE/measure.sh" drops | awk '{d += $5} END {print "kernel_drops total " d}'
    lowest "$log"
  done
done
