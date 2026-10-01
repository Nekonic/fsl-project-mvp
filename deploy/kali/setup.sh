set -eu
cd "$(dirname "$0")"

TTYD_VERSION=1.7.7
TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
APT="apt-get -y -o DPkg::Lock::Timeout=600"

export DEBIAN_FRONTEND=noninteractive
$APT update
$APT install \
  ca-certificates curl wget iptables \
  nmap sqlmap nikto whatweb ffuf gobuster hydra \
  netcat-traditional dnsutils jq wordlists dirb mitmproxy

[ -f /usr/share/wordlists/rockyou.txt.gz ] \
  && gunzip -f /usr/share/wordlists/rockyou.txt.gz || true

curl -fsSL -o /usr/local/bin/ttyd \
  "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64"
echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -
chmod +x /usr/local/bin/ttyd

install -d -m 0755 /etc/fsl /opt/fsl
install -m 0644 motd /etc/motd
install -m 0644 operator-log.sh /etc/fsl/operator-log.sh
install -m 0644 ../proxy/stamp.py /opt/fsl/stamp.py

install -d -m 0777 /label
: > /label/active
: > /label/origin
chmod 0666 /label/active /label/origin

cat > /etc/profile.d/fsl.sh <<'EOF'
export http_proxy="http://127.0.0.1:8081"
export HTTP_PROXY="http://127.0.0.1:8081"
export FSL_TARGET="http://shop.com"
export FSL_TARGET_HOST="shop.com"
EOF

cat >> /root/.bashrc <<'EOF'
. /etc/profile.d/fsl.sh
cat /etc/motd
. /etc/fsl/operator-log.sh
EOF

cat > /etc/systemd/system/fsl-proxy.service <<'EOF'
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/mitmdump -q --listen-port 8081 --set block_global=false -s /opt/fsl/stamp.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/fsl-terminal.service <<'EOF'
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/ttyd -W -b /terminal -p 7681 bash
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/cloud/cloud.cfg.d/99-fsl-user.cfg <<'EOF'
system_info:
  default_user:
    name: ubuntu
    gecos: FSL operator
    groups: [sudo]
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    shell: /bin/bash
EOF

systemctl enable fsl-proxy fsl-terminal
