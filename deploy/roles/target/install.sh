#!/bin/sh
set -eu
cd "$(dirname "$0")"

TAG=${CR_IMAGE_TAG:?set CR_IMAGE_TAG to the tag of the wargame images in GHCR}
WARGAMES="board corp"
BASE=/opt/wargames
KEPT=$BASE/pristine
BAKED=$BASE/baked.env
WAIT=900

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -y -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold"

installed() {
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    $APT update || :
    $APT install "$@" && return 0
    [ "$attempt" -lt 10 ] || return 1
    sleep 15
  done
}

ubuntu_trimmed() {
  sed -i -e 's/^Components:.*/Components: main restricted universe/' -e 's#^URIs:.*#URIs: http://mirror.kakao.com/ubuntu/#' /etc/apt/sources.list.d/ubuntu.sources
  $APT purge snapd modemmanager
  printf 'Package: snapd modemmanager\nPin: release *\nPin-Priority: -1\n' > /etc/apt/preferences.d/no-snapd-modemmanager
}

tenant_mtu() {
  cat "/sys/class/net/$(ip route show default | awk '{ print $5; exit }')/mtu"
}

compose() {
  wargame=$1
  shift
  docker compose -p "$wargame" --env-file "$BAKED" -f "$BASE/$wargame/compose.yaml" "$@"
}

pulled() {
  for attempt in 1 2 3 4 5; do
    compose "$1" pull --quiet && return 0
    [ "$attempt" -lt 5 ] || return 1
    sleep 10
  done
}

pristine_kept() {
  compose "$1" up -d --wait --wait-timeout "$WAIT" --pull never
  compose "$1" stop --timeout 120
  for service in $(compose "$1" config --services); do
    docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}} {{.Source}}{{println}}{{end}}{{end}}' \
      "$service" | while read -r path source; do
      [ -n "$path" ] || continue
      rm -rf "$KEPT/$service$path"
      mkdir -p "$KEPT/$service$path"
      cp -a "$source/." "$KEPT/$service$path/"
    done
  done
  compose "$1" down -v --timeout 1
}

sealed_for_snapshot() {
  cloud-init clean --logs
  : > /etc/machine-id
}

ubuntu_trimmed
installed docker.io docker-compose-v2 python3-yaml

MTU=${CR_MTU:-$(tenant_mtu)}
install -d -m 0755 /etc/docker "$BASE" "$KEPT"
printf '{"mtu": %s, "default-network-opts": {"bridge": {"com.docker.network.driver.mtu": "%s"}}, "log-driver": "local", "log-opts": {"max-size": "10m", "max-file": "2"}}\n' \
  "$MTU" "$MTU" > /etc/docker/daemon.json
systemctl enable docker.service
systemctl restart docker.service

composes=
for wargame in $WARGAMES; do
  composes="$composes $wargame.yaml"
done
python3 -I render.py --tag "$TAG" --mtu "$MTU" --settings wargames.yaml --into "$BASE" $composes
: > "$BAKED"
for wargame in $WARGAMES; do
  echo "$(echo "$wargame" | tr 'a-z-' 'A-Z_')_ADDRESS=127.0.0.1" >> "$BAKED"
done

for wargame in $WARGAMES; do
  pulled "$wargame"
done
for wargame in $WARGAMES; do
  pristine_kept "$wargame"
done

install -m 0755 wargames /usr/local/sbin/wargames
install -m 0644 wargames.service /etc/systemd/system/wargames.service
systemctl daemon-reload
systemctl enable wargames.service

sealed_for_snapshot
