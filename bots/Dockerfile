FROM python:3.13-slim

ARG CLAUDE_CODE_VERSION=2.1.331

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client sudo nodejs npm ca-certificates \
 && npm install -g --no-audit --no-fund @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
 && npm cache clean --force \
 && apt-get purge -y npm && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir requests==2.34.2 pyyaml==6.0.3

RUN useradd --system --uid 10001 --create-home launcher \
 && groupadd --system bots \
 && for number in 0 1 2 3 4 5 6 7; do \
      useradd --uid "$((11000 + number))" --create-home --groups bots --shell /bin/sh "bot$number" \
      && chmod 700 "/home/bot$number"; \
    done \
 && printf 'Defaults:launcher !lecture\nlauncher ALL=(%%bots) NOPASSWD:SETENV: ALL\n' > /etc/sudoers.d/launcher \
 && chmod 440 /etc/sudoers.d/launcher

WORKDIR /work
COPY bots/ /work/bots/
COPY openapi/schema.yaml /work/openapi/schema.yaml

USER launcher
ENV PYTHONPATH=/work PYTHONUNBUFFERED=1 CR_CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}
ENTRYPOINT ["python", "-m", "bots.launcher"]
