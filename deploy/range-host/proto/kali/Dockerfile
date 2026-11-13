FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's/^Components:.*/Components: main restricted universe multiverse/' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update \
 && apt-get install -y \
      ca-certificates curl wget iptables iproute2 sudo tzdata \
      nmap sqlmap nikto whatweb ffuf gobuster hydra \
      netcat-traditional dnsutils jq dirb mitmproxy \
 && rm -rf /var/lib/apt/lists/*

RUN f=$(dpkg -L sqlmap 2>/dev/null | grep -m1 'lib/core/settings\.py$' || true); [ -n "$f" ] && touch "$f" || true \
 && install -d -m 0755 /usr/share/wordlists \
 && ln -sfn /usr/share/dirb/wordlists /usr/share/wordlists/dirb

RUN ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime && echo Asia/Seoul > /etc/timezone && : > /etc/motd \
 && (userdel -r ubuntu 2>/dev/null || true) \
 && useradd --create-home --shell /bin/bash --groups sudo --comment Kali kali \
 && echo "kali ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-kali \
 && echo 'Defaults env_keep += "http_proxy HTTP_PROXY"' >> /etc/sudoers.d/90-kali \
 && chmod 0440 /etc/sudoers.d/90-kali && visudo -cf /etc/sudoers.d/90-kali \
 && touch /home/kali/.hushlogin && chown kali:kali /home/kali/.hushlogin

COPY --chown=kali:kali kali/bashrc /home/kali/.bashrc
COPY proxy/stamp.py /usr/local/lib/web-proxy.py
COPY kali/operator-log.sh /usr/local/lib/shell-hook.sh
COPY range-host/proto/kali/set-origin /usr/local/sbin/set-origin

RUN chmod 0755 /usr/local/sbin/set-origin \
 && install -d -m 0711 /var/lib/session \
 && install -m 0666 /dev/null /var/lib/session/active \
 && install -m 0622 /dev/null /var/log/commands.log \
 && echo '. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc \
 && printf 'export http_proxy="http://127.0.0.1:8081"\nexport HTTP_PROXY="http://127.0.0.1:8081"\n' > /etc/profile.d/proxy.sh

WORKDIR /home/kali
CMD ["/usr/bin/mitmdump", "-q", "--listen-port", "8081", "--set", "block_global=false", "-s", "/usr/local/lib/web-proxy.py"]
