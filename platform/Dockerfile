FROM python:3.13-slim

COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client gosu nginx curl ca-certificates tmux \
 && curl -fsSL -o /usr/local/bin/ttyd \
      https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
 && echo "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod +x /usr/local/bin/ttyd \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85,source=/uv,target=/bin/uv \
    --mount=type=bind,source=pyproject.toml,target=/lock/pyproject.toml --mount=type=bind,source=uv.lock,target=/lock/uv.lock \
    UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --inexact --no-default-groups --no-cache --compile-bytecode --project /lock
COPY platform/ .

RUN useradd --system --create-home --uid 10001 cr \
 && chown -R cr /app \
 && mkdir -p /data && chown cr /data \
 && chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
