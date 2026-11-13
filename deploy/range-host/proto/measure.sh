#!/bin/sh
set -eu
memory() {
  for id in $(docker ps -q --no-trunc); do
    project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$id")
    name=$(docker inspect -f '{{.Name}}' "$id")
    current=$(cat "/sys/fs/cgroup/system.slice/docker-$id.scope/memory.current" 2>/dev/null || echo 0)
    echo "$project ${name#/} $current"
  done | awk '{ by[$1] += $3; total += $3; printf "  %-14s %-22s %6.0f MiB\n", $1, $2, $3/1048576 }
              END { for (p in by) printf "project %-14s %6.0f MiB\n", p, by[p]/1048576; printf "all containers %6.0f MiB\n", total/1048576 }'
  free -m | awk 'NR==2 { printf "host used %s MiB, available %s MiB\n", $3, $7 }'
}
drops() {
  for c in $(docker ps --format '{{.Names}}' | grep -- '-sensor$'); do
    docker exec "$c" suricatasc -c dump-counters 2>/dev/null \
      | python3 -c "import json,sys; m=json.load(sys.stdin)['message']; m=m if isinstance(m,dict) else {}; c=m.get('capture',{}); print('$c', 'kernel_packets', c.get('kernel_packets'), 'kernel_drops', c.get('kernel_drops'), 'invalid_checksum', m.get('tcp',{}).get('invalid_checksum'), 'truncated', m.get('decoder',{}).get('event',{}).get('ipv4',{}).get('trunc_pkt'))"
  done
}
"$@"
