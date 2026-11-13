#!/bin/sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=/opt/proto
export CR_IMAGE_TAG=${CR_IMAGE_TAG:-3a0df7db325bdffe5b38e20ed9fb2ad51d616597}

now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.1f", b - a }'; }
pid() { docker inspect -f '{{.State.Pid}}' "$1"; }
inside() { c=$1; shift; nsenter -t "$(pid "$c")" -n "$@"; }
slot() { sn=$1; shift; N=$sn docker compose -p "s$sn" -f "$HERE/slot.yaml" "$@"; }

quiet_offloads() {
  for dev in $(inside "$1" ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1); do
    [ "$dev" = lo ] && continue
    inside "$1" ethtool -K "$dev" tso off gso off gro off >/dev/null 2>&1 || true
  done
}

show_offloads() {
  for c in $(docker ps --format '{{.Names}}' | grep "^s$1-" | grep -v sensor); do
    for dev in $(inside "$c" ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1); do
      [ "$dev" = lo ] && continue
      echo "$c $dev $(inside "$c" ethtool -k "$dev" | grep -E '^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|tx-checksumming):' | awk '{printf "%s=%s ", $1, $2}')"
    done
  done
}

quiet_host_offloads() {
  for dev in $(ls /sys/class/net); do
    case "$dev" in veth*|s$1-*) ethtool -K "$dev" tso off gso off gro off >/dev/null 2>&1 || true ;; esac
  done
}

prepare() {
  n=$1; d=$BASE/s$n
  install -d -m 0755 "$d" "$d/edge-log" "$d/estate-log" "$d/edge-rules" "$d/estate-rules"
  install -d -o 33 -g 4 -m 0750 "$d/waf"
  [ -f "$d/exclusions.conf" ] || install -m 0664 -g 4 /dev/null "$d/exclusions.conf"
  sed "s/SLOT/$n/g" "$HERE/edge-sensor.yaml" > "$d/edge-sensor.yaml"
  sed "s/SLOT/$n/g" "$HERE/estate-sensor.yaml" > "$d/estate-sensor.yaml"
  install -m 0644 "$HERE/../../suricata/rules/local.rules" "$d/edge-rules/local.rules"
  install -m 0644 "$HERE/../../suricata/rules/local.rules" "$d/estate-rules/local.rules"
}

bridges_forward() {
  for br in "s$1-inet" "s$1-estate"; do
    iptables -C DOCKER-USER -i "$br" -o "$br" -j ACCEPT 2>/dev/null \
      || iptables -I DOCKER-USER -i "$br" -o "$br" -j ACCEPT
  done
}

address_kali() {
  n=$1
  awk '{ for (i = 10; i < 10 + $2; i++) printf "addr add %s.%d/24 dev eth0\n", $1, i }
       END { print "route replace default via 36.128.0.1 dev eth0" }' "$HERE/origins.txt" > "$BASE/s$n/kali.ip"
  inside "s$n-kali" ip addr flush dev eth0
  inside "s$n-kali" ip -batch "$BASE/s$n/kali.ip"
  quiet_offloads "s$n-kali"
}

address_edge() {
  n=$1
  awk '{ printf "addr add %s.1/24 dev wan\n", $1 } END { print "addr del 172.30.N.1/24 dev wan" }' "$HERE/origins.txt" \
    | sed "s/\.N\./.$n./" > "$BASE/s$n/edge.ip"
  inside "s$n-edge" ip -batch "$BASE/s$n/edge.ip"
  quiet_offloads "s$n-edge"
}

address_waf() {
  inside "s$1-waf" ip route replace default via "10.30.$1.1"
  quiet_offloads "s$1-waf"
}

address_common() {
  n=$1
  address_kali "$n"; address_edge "$n"; address_waf "$n"
  quiet_host_offloads "$n"
}

up() {
  n=$1; t=$(now)
  prepare "$n"
  slot "$n" up -d --wait --quiet-pull
  address_common "$n"
  bridges_forward "$n"
  echo "up s$n $(since "$t")s"
}

down() {
  n=$1; t=$(now)
  for w in board corp; do target_down "$n" "$w" 2>/dev/null || true; done
  slot "$n" down -v --timeout 1
  echo "down s$n $(since "$t")s"
}

target() { tn=$1; tw=$2; shift 2; N=$tn docker compose -p "s$tn-$tw" -f "$HERE/$tw.yaml" "$@"; }

volumes() {
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}} {{.Source}}{{println}}{{end}}{{end}}' "$1"
}

keep() {
  n=$1; w=$2; kept=$BASE/pristine/$w
  target "$n" "$w" up -d --wait --quiet-pull
  target "$n" "$w" stop --timeout 120
  rm -rf "$kept"
  for svc in $(target "$n" "$w" config --services); do
    volumes "s$n-$svc" | while read -r path source; do
      [ -n "$path" ] || continue
      mkdir -p "$kept/$svc$path"
      cp -a "$source/." "$kept/$svc$path/"
    done
  done
  target "$n" "$w" down -v --timeout 1
}

attach() {
  n=$1; w=$2; kept=$BASE/pristine/$w; t=$(now)
  target "$n" "$w" up --no-start --quiet-pull
  for svc in $(target "$n" "$w" config --services); do
    volumes "s$n-$svc" | while read -r path source; do
      [ -n "$path" ] && [ -d "$kept/$svc$path" ] || continue
      [ -z "$(ls -A "$source")" ] || continue
      cp -a "$kept/$svc$path/." "$source/"
    done
  done
  target "$n" "$w" up -d --wait
  case "$w" in board) front=board ;; corp) front=corp-wp ;; esac
  inside "s$n-$front" ip route replace default via "10.30.$n.1" dev "$(inside "s$n-$front" ip -o addr show to "10.30.$n.0/24" | awk '{print $2}')"
  quiet_offloads "s$n-$front"
  quiet_host_offloads "$n"
  echo "attach s$n $w $(since "$t")s"
}

target_down() {
  n=$1; w=$2; t=$(now)
  target "$n" "$w" down -v --timeout 1
  echo "detach s$n $w $(since "$t")s"
}

reset() {
  n=$1; w=${2:-}; began=$(now)
  [ -z "$w" ] || target_down "$n" "$w" >/dev/null
  step=$(now); slot "$n" down -v --timeout 1 >/dev/null; downed=$(since "$step")
  rm -rf "$BASE/s$n/edge-log"/* "$BASE/s$n/estate-log"/* "$BASE/s$n/waf"/*
  step=$(now); up "$n" >/dev/null; upped=$(since "$step")
  step=$(now); [ -z "$w" ] || attach "$n" "$w" >/dev/null; attached=$(since "$step")
  echo "reset s$n ${w:-common} $(since "$began")s (common down ${downed}s, up ${upped}s, attach ${attached}s)"
}

reset_fast() {
  n=$1; w=$2; began=$(now)
  (
    step=$(now)
    target_down "$n" "$w" >/dev/null 2>&1
    attach "$n" "$w" >/dev/null 2>&1
    echo "target $(since "$step")s" > "$BASE/s$n/reset-target"
  ) &
  step=$(now)
  slot "$n" up -d --force-recreate --no-deps --wait kali waf >/dev/null 2>&1
  address_kali "$n"; address_waf "$n"; quiet_host_offloads "$n"
  inside "s$n-edge" ip neigh flush all
  for leg in edge estate; do
    : > "$BASE/s$n/$leg-log/eve.json"
    docker exec "s$n-$leg-sensor" suricatasc -c reopen-log-files >/dev/null
  done
  : > "$BASE/s$n/waf/audit.log" 2>/dev/null || true
  common=$(since "$step")
  wait
  echo "reset_fast s$n $w $(since "$began")s (kali and waf recreated ${common}s, $(cat "$BASE/s$n/reset-target"))"
}

"$@"
