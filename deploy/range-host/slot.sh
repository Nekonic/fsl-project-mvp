#!/bin/sh
set -eu

BASE=/opt/cr
KEPT=$BASE/pristine
WAIT=600
verb=${1:?slot.sh up|reset|down <slot>}
n=${2:?slot number}
d=$BASE/s$n
logs=/var/log/cr/s$n
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
  install -d -m 0755 "$d/edge-rules" "$d/estate-rules" "$logs" "$logs/edge" "$logs/estate" "$logs/waf"
  chown -h root:root "$logs/waf"
  find "$logs/waf" -mindepth 1 -maxdepth 1 ! \( -name audit.log -type f \) -exec rm -rf {} +
  [ -f "$logs/waf/audit.log" ] || install -m 0640 -o "$www" -g adm /dev/null "$logs/waf/audit.log"
  chmod 0640 "$logs/waf/audit.log"
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

rsyslog_restarted() {
  flock /run/cr-rsyslog.lock sh -c 'systemctl reset-failed rsyslog; systemctl restart rsyslog'
}

logs_forwarded() {
  forwarding=/etc/rsyslog.d/60-cr-$project.conf
  if cmp -s "$d/rsyslog.conf" "$forwarding" && systemctl is-active -q rsyslog; then
    return 0
  fi
  install -m 0644 "$d/rsyslog.conf" "$forwarding"
  rsyslogd -N1 >/dev/null
  rsyslog_restarted
}

logs_emptied() {
  for leg in edge estate; do
    : > "$logs/$leg/eve.json"
    docker exec "$project-$leg-sensor" suricatasc -c reopen-log-files >/dev/null
  done
  : > "$logs/waf/audit.log"
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
  rsyslog_restarted
  rm -rf "$d" "$logs"
}

case "$verb" in
  up|reset|down) "$verb" ;;
  *) echo "slot.sh up|reset|down <slot>" >&2; exit 2 ;;
esac
