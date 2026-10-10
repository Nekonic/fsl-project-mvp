#!/bin/sh
session="$1"
case "$session" in
  ""|*[!0-9]*) echo "no session given"; sleep 2; exit 1 ;;
esac
docker exec -it "fsl-${session}-waf-1" bash || { echo "session ${session} has no running WAF"; sleep 3; exit 1; }
