#!/bin/sh
set -eu
cd "$(dirname "$0")"

SENSOR_IMAGE=jasonish/suricata@sha256:7ca2546f7f2735f621b981b6a5ec84fb962984636f7629a1a2fa6a324d4b6840
EVE_DIR=/var/log/suricata
RULES_DIR=/var/lib/suricata/rules
SHARE=/usr/local/share/slot

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

pulled() {
  for attempt in 1 2 3 4 5; do
    docker pull -q "$1" && return 0
    [ "$attempt" -lt 5 ] || return 1
    sleep 10
  done
}

rsyslog_may_read_the_eve_log() {
  grep -qxF 'global(maxMessageSize="64k")' /etc/rsyslog.conf || sed -i '1i global(maxMessageSize="64k")' /etc/rsyslog.conf
  [ -f /etc/apparmor.d/usr.sbin.rsyslogd ] || return 0
  install -d /etc/apparmor.d/local
  printf '%s/eve.json r,\n' "$EVE_DIR" > /etc/apparmor.d/local/usr.sbin.rsyslogd
  systemctl reload apparmor
}

sealed_for_snapshot() {
  cloud-init clean --logs
  : > /etc/machine-id
}

ubuntu_trimmed
installed nftables iproute2 bridge-utils ethtool rsyslog docker.io

printf 'net.ipv4.ip_forward = 1\nnet.ipv4.conf.all.rp_filter = 0\nnet.ipv4.conf.default.rp_filter = 0\n' > /etc/sysctl.d/60-edge.conf
sysctl --system >/dev/null

install -d -m 0755 /etc/docker
install -m 0644 daemon.json /etc/docker/daemon.json
systemctl enable docker.service
systemctl restart docker.service
pulled "$SENSOR_IMAGE"

install -d -m 0755 /etc/suricata "$RULES_DIR" "$SHARE"
install -m 0644 suricata.yaml /etc/suricata/suricata.yaml
install -m 0644 local.rules "$RULES_DIR/local.rules"
install -d -m 2750 -g adm "$EVE_DIR"
docker run --rm --pull never -e PGID=4 \
  -v /etc/suricata/suricata.yaml:/etc/suricata/suricata.yaml \
  -v "$RULES_DIR:$RULES_DIR" \
  "$SENSOR_IMAGE" -T -c /etc/suricata/suricata.yaml

install -m 0755 suricatasc /usr/local/bin/suricatasc
install -m 0644 edge.nft log-relay.conf "$SHARE/"
install -m 0755 slot-boot /usr/local/sbin/slot-boot
install -m 0644 slot-boot.service sensor.service /etc/systemd/system/
rsyslog_may_read_the_eve_log

systemctl daemon-reload
systemctl disable nftables.service
systemctl enable rsyslog.service slot-boot.service sensor.service

sealed_for_snapshot
