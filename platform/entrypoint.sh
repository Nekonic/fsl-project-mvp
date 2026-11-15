#!/bin/sh
set -e

ELASTIC_KEPT=/data/elastic
ELASTIC_UID=1000
install -d -o "$ELASTIC_UID" -g 0 -m 700 "$ELASTIC_KEPT"
if [ ! -s "$ELASTIC_KEPT/elastic-password" ]; then
  (umask 077 && python -c 'import secrets; print(secrets.token_urlsafe(24))' > "$ELASTIC_KEPT/elastic-password.new")
  chown "$ELASTIC_UID:0" "$ELASTIC_KEPT/elastic-password.new"
  mv "$ELASTIC_KEPT/elastic-password.new" "$ELASTIC_KEPT/elastic-password"
fi

nginx -t -q -c /app/nginx.conf
(
  until python -c 'import socket; socket.create_connection(("127.0.0.1", 8001), 1).close()' 2>/dev/null; do
    sleep 1
  done
  exec nginx -c /app/nginx.conf
) &

gosu cr env TERMINAL_KEEP=1 ttyd -W -a -b /vm-terminal/kali -t disableResizeOverlay=true -t disableLeaveAlert=true -i 127.0.0.1 -p 7691 /app/vm-terminal.sh cr-kali &
gosu cr env TERMINAL_KEEP=1 ttyd -W -a -b /vm-terminal/waf -t disableResizeOverlay=true -t disableLeaveAlert=true -i 127.0.0.1 -p 7692 /app/vm-terminal.sh cr-waf &

ELASTIC_PASSWORD="$(cat "$ELASTIC_KEPT/elastic-password")"
export ELASTIC_PASSWORD

exec gosu cr sh -c '
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
    --clear-untrusted-proxy-headers cr.wsgi:application
'
