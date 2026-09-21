# The attacker's box, served into the browser by ttyd.
#
# Kali rather than a slim base carrying two tools: the red team window is
# meant to be the machine an attacker sits at, and an attacker does not sit at
# a machine with curl on it. The case buttons are a scripted baseline for
# scoring; this is where the work happens.
FROM kalilinux/kali-rolling

# Pin the official CDN. http.kali.org redirects to whichever mirror is near,
# and some of those serve https with a certificate the base image cannot
# verify - because ca-certificates is what we are here to install. The build
# then fails on a bootstrap loop that has nothing to do with this project.
RUN rm -f /etc/apt/sources.list.d/*.sources \
 && echo "deb http://kali.download/kali kali-rolling main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl wget \
      nmap sqlmap nikto whatweb ffuf gobuster hydra \
      netcat-traditional dnsutils jq nano wordlists dirb \
 && rm -rf /var/lib/apt/lists/*

# ttyd is not packaged in Kali, so take the upstream static build, pinned and
# checksummed. aarch64 only, which is what this stack already requires - see
# "The stack needs a native arm64 Docker host" in docs/DECISIONS.md.
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
RUN curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.aarch64" \
 && echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd

# `wordlists` is mostly symlinks into the packages that own each list, so the
# list a directory brute force reaches for only exists if dirb is installed -
# and rockyou ships gzipped, which no tool reads. Both fixed here rather than
# discovered at the prompt.
RUN [ -f /usr/share/wordlists/rockyou.txt.gz ] \
 && gunzip -f /usr/share/wordlists/rockyou.txt.gz || true

COPY motd /etc/motd
RUN echo 'cat /etc/motd' >> /root/.bashrc

WORKDIR /root

# -W makes the terminal writable; without it ttyd is read-only. There is no
# authentication and the shell is root: this is a single-host lab, on the same
# footing as the Docker socket the platform already mounts. Do not expose it.
EXPOSE 7681
CMD ["ttyd", "-W", "-p", "7681", "bash"]
