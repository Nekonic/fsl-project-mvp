# The attacker's shell, served into the browser by ttyd.
#
# Kali rather than a slim base carrying the same tools: the point of the red
# team window is that it is the box an attacker would sit at, and the case
# buttons beside it already cover the scripted half.
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
      curl nmap sqlmap ca-certificates \
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

WORKDIR /root

# -W makes the terminal writable; without it ttyd is read-only. There is no
# authentication and the shell is root: this is a single-host lab, on the same
# footing as the Docker socket the platform already mounts. Do not expose it.
EXPOSE 7681
CMD ["ttyd", "-W", "-p", "7681", "bash"]
