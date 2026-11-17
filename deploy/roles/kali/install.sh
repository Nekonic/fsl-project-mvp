#!/bin/sh
set -eu
cd "$(dirname "$0")"

ROUTER=121.134.88.42
PROXY_PORT=8081
TOOLS="nmap sqlmap nikto whatweb ffuf gobuster hydra netcat-traditional dnsutils jq dirb mitmproxy"
SYSTEM="ca-certificates curl wget iptables iproute2 sudo tzdata procps less nano iputils-ping traceroute python3 openssh-server"

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

sites_named() {
  [ -f "$1" ] || return 0
  sed -i -e '/[[:space:]]board\.com[[:space:]]*$/d' -e '/[[:space:]]corp\.com[[:space:]]*$/d' "$1"
  printf '%s board.com\n%s corp.com\n' "$ROUTER" "$ROUTER" >> "$1"
}

key_only_login_for() {
  id -u "$1" >/dev/null 2>&1 || useradd -m -U -s /bin/bash -G adm,audio,cdrom,dialout,dip,floppy,plugdev,sudo,video "$1"
  usermod -s /bin/bash "$1"
  passwd -l "$1"
  printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$1" > /etc/sudoers.d/90-default-user
  chmod 0440 /etc/sudoers.d/90-default-user
  visudo -cq
  home=$(getent passwd "$1" | cut -d: -f6)
  install -d -m 0700 -o "$1" -g "$(id -gn "$1")" "$home/.ssh"
  [ -f "$home/.ssh/authorized_keys" ] || install -m 0600 -o "$1" -g "$(id -gn "$1")" /dev/null "$home/.ssh/authorized_keys"
  printf 'PubkeyAuthentication yes\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' > /etc/ssh/sshd_config.d/10-key-only.conf
  sshd -t
}

bashrc_for() {
  home=$(getent passwd "$1" | cut -d: -f6)
  [ -n "$home" ] && [ -d "$home" ] || return 0
  install -m 0644 -o "$1" -g "$(id -gn "$1")" bashrc "$home/.bashrc"
}

sealed_for_snapshot() {
  cloud-init clean --logs
  : > /etc/machine-id
}

installed kali-linux-headless $SYSTEM $TOOLS

settings=$(dpkg -L sqlmap 2>/dev/null | grep -m1 'lib/core/settings\.py$' || true)
[ -z "$settings" ] || touch "$settings"
install -d -m 0755 /usr/share/wordlists
[ -e /usr/share/wordlists/dirb ] || ln -s /usr/share/dirb/wordlists /usr/share/wordlists/dirb

ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime
echo Asia/Seoul > /etc/timezone
: > /etc/motd
touch /root/.hushlogin

install -m 0644 bashrc /root/.bashrc
install -m 0644 bashrc /etc/skel/.bashrc
key_only_login_for kali
bashrc_for kali

install -m 0644 stamp.py /usr/local/lib/web-proxy.py
install -m 0644 operator-log.sh /usr/local/lib/shell-hook.sh
install -m 0755 set-origin /usr/local/sbin/set-origin
install -m 0755 slot-boot /usr/local/sbin/slot-boot
install -d -m 0711 /var/lib/session
install -m 0600 /dev/null /var/lib/session/active
install -m 0622 /dev/null /var/log/commands.log
grep -qxF '. /usr/local/lib/shell-hook.sh' /etc/bash.bashrc || echo '. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc
printf 'export http_proxy="http://127.0.0.1:%s"\nexport HTTP_PROXY="http://127.0.0.1:%s"\n' "$PROXY_PORT" "$PROXY_PORT" > /etc/profile.d/proxy.sh

sites_named /etc/hosts
sites_named /etc/cloud/templates/hosts.debian.tmpl

install -m 0644 web-proxy.service slot-boot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ssh.service web-proxy.service slot-boot.service
systemctl restart web-proxy.service
systemctl is-active --quiet web-proxy.service

sealed_for_snapshot
