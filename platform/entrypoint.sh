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

nginx -c /app/nginx.conf

gosu fsl ttyd -W -b /vm-terminal/fsl-kali -i 127.0.0.1 -p 7691 /app/vm-terminal.sh fsl-kali &
gosu fsl ttyd -W -b /vm-terminal/fsl-waf -i 127.0.0.1 -p 7692 /app/vm-terminal.sh fsl-waf &

exec gosu fsl sh -c '
  python manage.py migrate --noinput
  python register_pipeline.py
  exec waitress-serve --listen=127.0.0.1:8001 --threads=8 \
    --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for \
    --clear-untrusted-proxy-headers fsl.wsgi:application
'
