#!/bin/sh
n=${1:-1}; other=${2:-2}
probe() {
  box=$1; want=$2; what=$3; shift 3
  if docker exec "$box" timeout 5 "$@" >/dev/null 2>&1; then got=reached; else got=refused; fi
  [ "$got" = "$want" ] && verdict=ok || verdict=FAIL
  echo "$verdict $box $what: $got (want $want)"
}
for box in "s$n-kali" "s$n-waf"; do
  probe "$box" refused "s$other estate WAF 10.30.$other.247:80" curl -s -m3 -o /dev/null "http://10.30.$other.247/"
  probe "$box" refused "s$other estate board 10.30.$other.59:8000" curl -s -m3 -o /dev/null "http://10.30.$other.59:8000/"
  probe "$box" refused "range host 10.20.0.41:22" curl -s -m3 -o /dev/null telnet://10.20.0.41:22
  probe "$box" refused "range host docker0 172.17.0.1:22" curl -s -m3 -o /dev/null telnet://172.17.0.1:22
  probe "$box" refused "s$n estate bridge gateway 10.30.$n.254:22" curl -s -m3 -o /dev/null telnet://10.30.$n.254:22
  probe "$box" refused "platform mgmt 10.31.0.88:8000" curl -s -m3 -o /dev/null http://10.31.0.88:8000/
  probe "$box" refused "platform 10.20.0.74:8000" curl -s -m3 -o /dev/null http://10.20.0.74:8000/
  probe "$box" refused "platform 192.168.2.247:8000" curl -s -m3 -o /dev/null http://192.168.2.247:8000/
  probe "$box" refused "metadata 169.254.169.254" curl -s -m3 -o /dev/null http://169.254.169.254/
  probe "$box" refused "Internet 1.1.1.1:443" curl -s -m3 -o /dev/null telnet://1.1.1.1:443
  probe "$box" refused "Internet ghcr.io" curl -s -m3 -o /dev/null https://ghcr.io/
done
probe "s$n-kali" refused "board-db 3306 from kali" sh -c "getent hosts s$n-board-db || exit 1"
probe "s$n-kali" reached "board.com through the WAF" curl -sf -m5 -o /dev/null http://board.com/
probe "s$n-kali" reached "board directly through the edge" curl -sf -m5 -o /dev/null http://board:8000/
for box in $(docker ps --format '{{.Names}}' | grep -E "^s$n-(board|corp-wp)$"); do
  probe "$box" refused "range host 10.20.0.41:22 from the target" bash -c "exec 3<>/dev/tcp/10.20.0.41/22" 
  probe "$box" refused "range host 172.17.0.1:22 from the target" bash -c "exec 3<>/dev/tcp/172.17.0.1/22"
  probe "$box" refused "Internet 1.1.1.1:443 from the target" bash -c "exec 3<>/dev/tcp/1.1.1.1/443"
done
for br in $(ip -4 -o addr show | awk '/br-/ {print $4}' | cut -d/ -f1); do echo "WARN host address on a docker bridge: $br"; done
