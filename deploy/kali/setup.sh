set -eu
cd "$(dirname "$0")"

TTYD_VERSION=1.7.7
TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
APT="apt-get -y -o DPkg::Lock::Timeout=600"

export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components:.*/Components: main restricted universe multiverse/' \
  /etc/apt/sources.list.d/ubuntu.sources
$APT update
$APT install \
  ca-certificates curl wget iptables \
  nmap sqlmap nikto whatweb ffuf gobuster hydra \
  netcat-traditional dnsutils jq dirb mitmproxy

f=$(dpkg -L sqlmap 2>/dev/null | grep -m1 'lib/core/settings\.py$' || true)
[ -n "$f" ] && touch "$f" || true

install -d -m 0755 /usr/share/wordlists
ln -sfn /usr/share/dirb/wordlists /usr/share/wordlists/dirb

curl -fsSL -o /usr/local/bin/ttyd \
  "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64"
echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -
chmod +x /usr/local/bin/ttyd

echo "127.0.1.1 kali" >> /etc/hosts
echo kali > /etc/hostname
hostname kali
echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99-hostname.cfg

ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime
echo Asia/Seoul > /etc/timezone
: > /etc/motd

useradd --create-home --shell /bin/bash --groups sudo --comment Kali kali
echo "kali ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-kali
chmod 0440 /etc/sudoers.d/90-kali
visudo -cf /etc/sudoers.d/90-kali
install -o kali -g kali -m 0644 bashrc /home/kali/.bashrc
touch /home/kali/.hushlogin
chown kali:kali /home/kali/.hushlogin

cat > /etc/ssh/sshd_config.d/60-kali.conf <<'SSHD'
Match User kali
    AuthorizedKeysCommand /usr/bin/cat /home/ubuntu/.ssh/authorized_keys
    AuthorizedKeysCommandUser root
SSHD
install -d -m 0755 /run/sshd
sshd -t

install -m 0644 ../proxy/stamp.py /usr/local/lib/web-proxy.py
install -m 0644 operator-log.sh /usr/local/lib/shell-hook.sh

cat > /usr/local/sbin/set-origin <<'ORIGIN'
#!/bin/sh
set -eu
source=${1-}
dev=$(ip route show default | awk '{print $5; exit}')
iptables -t nat -N ORIGIN-SNAT 2>/dev/null || iptables -t nat -F ORIGIN-SNAT
iptables -t nat -C POSTROUTING -o "$dev" -j ORIGIN-SNAT 2>/dev/null \
  || iptables -t nat -A POSTROUTING -o "$dev" -j ORIGIN-SNAT
[ -n "$source" ] && iptables -t nat -A ORIGIN-SNAT -j SNAT --to-source "$source"
exit 0
ORIGIN
chmod 0755 /usr/local/sbin/set-origin

install -d -m 0711 /var/lib/session
install -m 0600 -o ubuntu -g ubuntu /dev/null /var/lib/session/active
install -m 0600 -o ubuntu -g ubuntu /dev/null /var/lib/session/origin

install -m 0622 -o ubuntu -g ubuntu /dev/null /var/log/commands.log
echo '. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc

cat > /etc/profile.d/proxy.sh <<'EOF'
export http_proxy="http://127.0.0.1:8081"
export HTTP_PROXY="http://127.0.0.1:8081"
EOF

cat > /etc/systemd/system/web-proxy.service <<'EOF'
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/mitmdump -q --listen-port 8081 --set block_global=false -s /usr/local/lib/web-proxy.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ttyd.service <<'EOF'
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/ttyd -W -t disableResizeOverlay=true -b /terminal -p 7681 bash
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl enable web-proxy ttyd
