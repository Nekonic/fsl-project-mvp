FROM python:3.13-slim

COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ARG DOCKER_GID=0
RUN useradd --system --create-home --uid 10001 fsl \
 && groupadd --gid ${DOCKER_GID} dockersock \
 && usermod --append --groups dockersock fsl \
 && chown -R fsl /app
USER fsl

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec waitress-serve --listen=0.0.0.0:8000 --threads=8 fsl.wsgi:application"]
