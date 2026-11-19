FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client openssh-server gosu nginx curl ca-certificates tmux \
 && curl -fsSL -o /usr/local/bin/ttyd \
      https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
 && echo "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*

WORKDIR /app
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85,source=/uv,target=/bin/uv \
    --mount=type=bind,source=pyproject.toml,target=/lock/pyproject.toml --mount=type=bind,source=uv.lock,target=/lock/uv.lock \
    UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --inexact --no-default-groups --no-cache --compile-bytecode --project /lock
COPY platform/ .
COPY strings/server.json /strings/server.json

RUN useradd --system --create-home --uid 10001 cr \
 && useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --password '*' jump \
 && chown -R cr /app \
 && mkdir -p /data && chown cr /data \
 && chmod +x entrypoint.sh

EXPOSE 8000 2222
ENTRYPOINT ["/app/entrypoint.sh"]
