#!/bin/sh
set -eu

BASE=/opt/cr
KEPT=$BASE/pristine
WAIT=600
verb=${1:?slot.sh up|reset|down|play <slot> [service...]}
n=${2:?slot number}
d=$BASE/s$n
logs=/var/log/cr/s$n
project=s$n

compose() { docker compose -p "$project" -f "$d/compose.yaml" "$@"; }
pid() { docker inspect -f '{{.State.Pid}}' "$1"; }
inside() { c=$1; shift; nsenter -t "$(pid "$c")" -n "$@"; }
wargames() { cat "$BASE/wargames.txt"; }
logging() { compose config --services | grep -e '^log-server$' -e '-shipper$'; }
fronts() { cat "$d/fronts"; }
remapped() { awk -F: '$1 == "dockremap" { print $2; exit }' /etc/subuid 2>/dev/null; }

volumes() {
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}} {{.Source}}{{println}}{{end}}{{end}}' "$1"
}

quiet() {
  for dev in $(inside "$1" ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1); do
    [ "$dev" = lo ] && continue
    inside "$1" ethtool -K "$dev" tso off gso off gro off >/dev/null 2>&1 || true
  done
}

quieted() {
  for service in "$@"; do
    quiet "$project-$service"
  done
}

quiet_bridges() {
  for bridge in "s$n-inet" "s$n-estate" "s$n-web"; do
    ethtool -K "$bridge" tso off gso off gro off >/dev/null 2>&1 || true
    for port in $(ls "/sys/class/net/$bridge/brif" 2>/dev/null); do
      ethtool -K "$port" tso off gso off gro off >/dev/null 2>&1 || true
    done
  done
}

forwarded() {
  for bridge in "s$n-inet" "s$n-estate" "s$n-web"; do
    iptables -C DOCKER-USER -i "$bridge" -o "$bridge" -j ACCEPT 2>/dev/null \
      || iptables -I DOCKER-USER -i "$bridge" -o "$bridge" -j ACCEPT 2>/dev/null || true
  done
}

named() {
  grep -q "[[:space:]]$(hostname)\$" /etc/hosts || printf '127.0.1.1 %s\n' "$(hostname)" >> /etc/hosts
}

prepare() {
  named
  shift_by=$(remapped)
  owner=$(( ${shift_by:-0} ))
  www=$(( ${shift_by:-0} + 33 ))
  adm=$(( ${shift_by:-0} + 4 ))
  install -d -m 0755 "$d/sensor-rules" "$logs" "$logs/sensor" "$logs/waf"
  chown -h root:root "$logs/waf"
  find "$logs/waf" -mindepth 1 -maxdepth 1 ! \( \( -name audit.log -o -name refused.log \) -type f \) -exec rm -rf {} +
  for log in audit.log refused.log; do
    [ -f "$logs/waf/$log" ] || install -m 0644 -o "$www" -g "$adm" /dev/null "$logs/waf/$log"
    chown -h "$www:$adm" "$logs/waf/$log"
    chmod 0644 "$logs/waf/$log"
  done
  install -m 0644 -o "$owner" -g "$owner" "$d/local.rules" "$d/sensor-rules/local.rules"
  chown -h "$owner:$owner" "$d/sensor.yaml" "$d/sensor-rules" "$logs/sensor"
}

restore() {
  for service in "$@"; do
    container=$project-$service
    [ "$(docker inspect --format '{{.State.Status}}' "$container")" = created ] || continue
    volumes "$container" | while read -r path source; do
      [ -n "$path" ] && [ -d "$KEPT/$service$path" ] || continue
      [ -z "$(ls -A "$source")" ] || continue
      cp -a "$KEPT/$service$path/." "$source/"
    done
  done
}

routed() {
  gateway=$(cat "$d/gateway")
  for service in "$@"; do
    inside "$project-$service" ip route replace default via "$gateway"
    quiet "$project-$service"
  done
}

address_kali() {
  inside "$project-kali" ip addr flush dev eth0
  inside "$project-kali" ip -batch "$d/kali.ip"
  quiet "$project-kali"
}

address_edge() {
  inside "$project-edge" ip addr flush dev wan
  inside "$project-edge" ip -batch "$d/edge.ip"
  quiet "$project-edge"
}

peer() {
  inside "$1" ip -o link show dev "$2" | sed -n 's/^[0-9]*: [^@:]*@if\([0-9]*\):.*/\1/p'
}

port_of() {
  at=$(peer "$1" "$2")
  ip -o link show | awk -F': ' -v at="$at" '$1 == at { split($2, name, "@"); print name[1] }'
}

spanned() {
  bridge=s$n-$1
  sensor=$(port_of "$project-sensor" "$2")
  [ -n "$sensor" ]
  inside "$project-sensor" ip addr flush dev "$2"
  bridge link set dev "$sensor" learning off flood off mcast_flood off bcast_flood off
  for port in $(ls "/sys/class/net/$bridge/brif"); do
    tc qdisc replace dev "$port" clsact
    tc filter del dev "$port" ingress 2>/dev/null || true
    if [ "$port" = "$sensor" ]; then
      tc filter add dev "$port" ingress matchall action drop
    else
      tc filter add dev "$port" ingress matchall action mirred egress mirror dev "$sensor"
    fi
  done
}

mirrored() {
  for bridge in inet estate; do
    for port in $(ls "/sys/class/net/s$n-$bridge/brif" 2>/dev/null); do
      tc qdisc del dev "$port" clsact 2>/dev/null || true
    done
  done
  spanned web web
}

kept() {
  iptables -C "$@" 2>/dev/null || iptables -I "$@"
}

uplinked() {
  read -r server collector port < "$d/uplink"
  bridge=s$n-mgmt
  kept INPUT -i "$bridge" -j DROP
  kept DOCKER-USER -i "$bridge" -j DROP
  kept DOCKER-USER -i "$bridge" -s "$server" -d "$collector" -p udp --dport "$port" -j ACCEPT
  kept DOCKER-USER -i "$bridge" -o "$bridge" -j ACCEPT
}

unlinked() {
  for chain in INPUT DOCKER-USER; do
    iptables -S "$chain" | grep -- "-i s$n-mgmt " | sed 's/^-A //' | while read -r rule; do
      iptables -D $rule
    done
  done
}

logs_emptied() {
  : > "$logs/sensor/eve.json"
  docker exec "$project-sensor" suricatasc -c reopen-log-files >/dev/null
}

up() {
  prepare
  uplinked
  compose up --no-start --pull never --remove-orphans
  restore $(wargames)
  compose up -d --wait --wait-timeout "$WAIT" --pull never
  compose up -d --force-recreate --no-deps --wait --wait-timeout "$WAIT" --pull never sensor $(logging)
  address_kali
  address_edge
  routed waf
  quieted $(fronts)
  quiet_bridges
  forwarded
  mirrored
}

targets_reset() {
  compose rm -sfv $(wargames)
  compose up --no-start --pull never $(wargames)
  restore $(wargames)
  compose up -d --wait --wait-timeout "$WAIT" --pull never --no-deps $(wargames)
  quieted $(fronts)
}

reset() {
  prepare
  targets_reset > "$d/targets.log" 2>&1 &
  targets=$!
  : > "$logs/waf/audit.log"
  : > "$logs/waf/refused.log"
  compose up -d --force-recreate --no-deps --wait --wait-timeout "$WAIT" --pull never kali waf waf-shipper
  address_kali
  routed waf
  inside "$project-edge" ip neigh flush all
  logs_emptied
  if ! wait "$targets"; then
    cat "$d/targets.log" >&2
    exit 1
  fi
  quiet_bridges
  forwarded
  mirrored
}

play() {
  stopped=
  for service in $(wargames); do
    case " $* " in
      *" $service "*) ;;
      *) stopped="$stopped $service" ;;
    esac
  done
  [ -z "$stopped" ] || compose stop -t 1 $stopped
}

down() {
  [ ! -f "$d/compose.yaml" ] || compose down -v --remove-orphans --timeout 1
  unlinked
  rm -rf "$d" "$logs"
}

case "$verb" in
  up|reset|down) "$verb" ;;
  play) shift 2; play "$@" ;;
  *) echo "slot.sh up|reset|down|play <slot> [service...]" >&2; exit 2 ;;
esac
