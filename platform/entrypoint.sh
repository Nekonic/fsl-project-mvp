#!/bin/sh
set -e

SOCK=/var/run/docker.sock
if [ -S "$SOCK" ]; then
  gid=$(stat -c %g "$SOCK")
  if [ "$gid" != 0 ] && ! getent group "$gid" >/dev/null; then
    groupadd -g "$gid" dockersock
  fi
  group=$(getent group "$gid" | cut -d: -f1)
  if [ -n "$group" ] && ! id -nG fsl | tr ' ' '\n' | grep -qx "$group"; then
    usermod -aG "$group" fsl
  fi
fi

nginx -t -q -c /app/nginx.conf
(
  until python -c 'import socket; socket.create_connection(("127.0.0.1", 8001), 1).close()' 2>/dev/null; do
    sleep 1
  done
  exec nginx -c /app/nginx.conf
) &

gosu fsl ttyd -W -a -b /vm-terminal/kali -t disableResizeOverlay=true -i 127.0.0.1 -p 7691 /app/vm-terminal.sh fsl-kali &
gosu fsl ttyd -W -a -b /vm-terminal/waf -t disableResizeOverlay=true -i 127.0.0.1 -p 7692 /app/vm-terminal.sh fsl-waf &

exec gosu fsl sh -c '
  if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
    [ -s /data/secret-key ] || (umask 077 && python -c "import secrets; print(secrets.token_urlsafe(50))" > /data/secret-key)
    DJANGO_SECRET_KEY="$(cat /data/secret-key)"
    export DJANGO_SECRET_KEY
  fi
  python manage.py migrate --noinput
  python register_pipeline.py &
  python kibana.py &
  exec waitress-serve --listen=127.0.0.1:8001 --threads=16 \
    --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for \
    --clear-untrusted-proxy-headers fsl.wsgi:application
'
