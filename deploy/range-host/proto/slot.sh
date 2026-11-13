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

address_common() {
  n=$1
  inside "s$n-kali" ip addr flush dev eth0
  while read -r prefix count; do
    i=10
    while [ "$i" -lt $((10 + count)) ]; do
      inside "s$n-kali" ip addr add "$prefix.$i/24" dev eth0
      i=$((i + 1))
    done
    inside "s$n-edge" ip addr add "$prefix.1/24" dev wan 2>/dev/null || true
  done < "$HERE/origins.txt"
  inside "s$n-edge" ip addr del "172.30.$n.1/24" dev wan 2>/dev/null || true
  inside "s$n-kali" ip route replace default via 36.128.0.1 dev eth0
  inside "s$n-waf" ip route replace default via "10.30.$n.1"
  for c in kali edge waf; do quiet_offloads "s$n-$c"; done
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
  n=$1; w=${2:-}; t=$(now)
  [ -z "$w" ] || target_down "$n" "$w" >/dev/null
  slot "$n" down -v --timeout 1 >/dev/null
  rm -rf "$BASE/s$n/edge-log"/* "$BASE/s$n/estate-log"/* "$BASE/s$n/waf"/*
  up "$n" >/dev/null
  [ -z "$w" ] || attach "$n" "$w" >/dev/null
  echo "reset s$n ${w:-common} $(since "$t")s"
}

"$@"
