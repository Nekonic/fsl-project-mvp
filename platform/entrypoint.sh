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

exec gosu fsl sh -c '
  python manage.py migrate --noinput
  python register_pipeline.py
  exec waitress-serve --listen=0.0.0.0:8000 --threads=8 fsl.wsgi:application
'
