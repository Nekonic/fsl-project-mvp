#!/bin/sh
n=${1:-1}
timed() { t=$(date +%s.%N); out=$("$@" 2>&1); echo "$(awk -v a="$t" -v b="$(date +%s.%N)" 'BEGIN { printf "%.2f", b - a }')s $(echo "$out" | tr '\n' ' ' | cut -c1-120)"; }
echo 'alert http $EXTERNAL_NET any -> $HOME_NET any (msg:"proto reload probe"; flow:established,to_server; http.uri; content:"/proto-reload-probe"; sid:9900001; rev:1;)' >> "/opt/proto/s$n/edge-rules/local.rules"
for i in 1 2 3; do echo "edge-sensor reload-rules $(timed docker exec "s$n-edge-sensor" suricatasc -c reload-rules)"; done
for i in 1 2 3; do echo "estate-sensor reload-rules $(timed docker exec "s$n-estate-sensor" suricatasc -c reload-rules)"; done
for i in 1 2 3; do echo "waf nginx -t && reload $(timed docker exec "s$n-waf" sh -c 'nginx -t 2>&1 && nginx -s reload 2>&1')"; done
docker exec -u kali "s$n-kali" curl -s -o /dev/null http://board.com/proto-reload-probe
sleep 2
grep -c '"signature_id":9900001' "/opt/proto/s$n/edge-log/eve.json" | sed 's/^/new rule alerts after reload: /'
sed -i '/sid:9900001;/d' "/opt/proto/s$n/edge-rules/local.rules"
docker exec "s$n-edge-sensor" suricatasc -c reload-rules >/dev/null
