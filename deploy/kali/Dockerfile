FROM kalilinux/kali-rolling

RUN rm -f /etc/apt/sources.list.d/*.sources \
 && echo "deb http://kali.download/kali kali-rolling main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl wget sudo tzdata \
      nmap sqlmap nikto whatweb ffuf gobuster hydra \
      netcat-traditional dnsutils jq nano wordlists dirb \
 && rm -rf /var/lib/apt/lists/*

ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
RUN curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
 && echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd

RUN [ -f /usr/share/wordlists/rockyou.txt.gz ] \
 && gunzip -f /usr/share/wordlists/rockyou.txt.gz || true

RUN f="$(dpkg -L sqlmap 2>/dev/null | grep -m1 'lib/core/settings\.py$')"; [ -n "$f" ] && touch "$f" || true

RUN useradd --create-home --shell /bin/bash --groups sudo --comment Kali kali \
 && echo "kali ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-kali \
 && chmod 0440 /etc/sudoers.d/90-kali \
 && ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime \
 && echo Asia/Seoul > /etc/timezone \
 && : > /etc/motd

COPY --chown=kali:kali bashrc /home/kali/.bashrc
COPY operator-log.sh /usr/local/lib/shell-hook.sh
RUN : > /var/log/commands.log \
 && chmod 0666 /var/log/commands.log \
 && echo '. /usr/local/lib/shell-hook.sh' >> /etc/bash.bashrc

WORKDIR /home/kali

EXPOSE 7681
CMD ["ttyd", "-W", "-t", "disableResizeOverlay=true", "-b", "/terminal", "-p", "7681", "su", "kali"]
