FROM kalilinux/kali-rolling

RUN rm -f /etc/apt/sources.list.d/*.sources \
 && echo "deb http://kali.download/kali kali-rolling main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl wget \
      nmap sqlmap nikto whatweb ffuf gobuster hydra \
      netcat-traditional dnsutils jq nano wordlists dirb \
 && rm -rf /var/lib/apt/lists/*

ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
RUN curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.aarch64" \
 && echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd

RUN [ -f /usr/share/wordlists/rockyou.txt.gz ] \
 && gunzip -f /usr/share/wordlists/rockyou.txt.gz || true

COPY motd /etc/motd
COPY operator-log.sh /etc/fsl/operator-log.sh
RUN mkdir -p /var/log/fsl \
 && echo 'cat /etc/motd' >> /root/.bashrc \
 && echo '. /etc/fsl/operator-log.sh' >> /root/.bashrc

WORKDIR /root

EXPOSE 7681
CMD ["ttyd", "-W", "-p", "7681", "bash"]
