FROM python:3.13-slim

ARG DOCKER_GID
RUN [ -n "$DOCKER_GID" ] || { echo 'DOCKER_GID is empty, so the platform could not reach the docker socket. Build with DOCKER_GID=$(bin/docker-gid) docker compose up -d --build' >&2; exit 1; }

COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --system --create-home --uid 10001 fsl \
 && (getent group ${DOCKER_GID} || groupadd --gid ${DOCKER_GID} dockersock) \
 && usermod --append --groups $(getent group ${DOCKER_GID} | cut -d: -f1) fsl \
 && chown -R fsl /app
USER fsl

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec waitress-serve --listen=0.0.0.0:8000 --threads=8 fsl.wsgi:application"]
