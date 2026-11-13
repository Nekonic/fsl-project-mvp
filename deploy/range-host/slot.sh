#!/bin/sh
set -eu

BASE=/opt/cr
KEPT=$BASE/pristine
WAIT=600
verb=${1:?slot.sh up|reset|down <slot>}
n=${2:?slot number}
d=$BASE/s$n
project=s$n

compose() { docker compose -p "$project" -f "$d/compose.yaml" "$@"; }
pid() { docker inspect -f '{{.State.Pid}}' "$1"; }
inside() { c=$1; shift; nsenter -t "$(pid "$c")" -n "$@"; }
wargames() { cat "$BASE/wargames.txt"; }
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

quiet_bridges() {
  for bridge in "s$n-inet" "s$n-estate"; do
    ethtool -K "$bridge" tso off gso off gro off >/dev/null 2>&1 || true
    for port in $(ls "/sys/class/net/$bridge/brif" 2>/dev/null); do
      ethtool -K "$port" tso off gso off gro off >/dev/null 2>&1 || true
    done
  done
}

forwarded() {
  for bridge in "s$n-inet" "s$n-estate"; do
    iptables -C DOCKER-USER -i "$bridge" -o "$bridge" -j ACCEPT 2>/dev/null \
      || iptables -I DOCKER-USER -i "$bridge" -o "$bridge" -j ACCEPT 2>/dev/null || true
  done
}

prepare() {
  shift_by=$(remapped)
  owner=$(( ${shift_by:-0} ))
  www=$(( ${shift_by:-0} + 33 ))
  install -d -m 0755 "$d/edge-log" "$d/estate-log" "$d/edge-rules" "$d/estate-rules"
  install -d -m 0750 -o "$www" -g 4 "$d/waf-audit"
  for leg in edge estate; do
    install -m 0644 -o "$owner" "$d/local.rules" "$d/$leg-rules/local.rules"
  done
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

logs_forwarded() {
  install -m 0644 "$d/rsyslog.conf" "/etc/rsyslog.d/60-cr-$project.conf"
  rsyslogd -N1 >/dev/null
  systemctl restart rsyslog
}

logs_emptied() {
  for leg in edge estate; do
    : > "$d/$leg-log/eve.json"
    docker exec "$project-$leg-sensor" suricatasc -c reopen-log-files >/dev/null
  done
  [ ! -f "$d/waf-audit/audit.log" ] || : > "$d/waf-audit/audit.log"
}

up() {
  prepare
  compose up --no-start --pull never
  restore $(wargames)
  compose up -d --wait --wait-timeout "$WAIT" --pull never
  address_kali
  address_edge
  routed waf $(fronts)
  quiet_bridges
  forwarded
  logs_forwarded
}

targets_reset() {
  compose rm -sfv $(wargames)
  compose up --no-start --pull never $(wargames)
  restore $(wargames)
  compose up -d --wait --wait-timeout "$WAIT" --pull never --no-deps $(wargames)
  routed $(fronts)
}

reset() {
  prepare
  targets_reset > "$d/targets.log" 2>&1 &
  targets=$!
  compose up -d --force-recreate --no-deps --wait --wait-timeout "$WAIT" --pull never kali waf
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
}

down() {
  [ ! -f "$d/compose.yaml" ] || compose down -v --remove-orphans --timeout 1
  rm -f "/etc/rsyslog.d/60-cr-$project.conf"
  systemctl restart rsyslog
  rm -rf "$d"
}

case "$verb" in
  up|reset|down) "$verb" ;;
  *) echo "slot.sh up|reset|down <slot>" >&2; exit 2 ;;
esac
