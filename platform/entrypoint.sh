#!/bin/sh
set -e

for host in $(printf '%s' "${DJANGO_ALLOWED_HOSTS:-}" | tr ',' ' '); do
  case "$host" in
    *[!0-9.]*) ;;
    *) printf '%s 1;\n' "$host" ;;
  esac
done > /tmp/nginx-platform-addresses.conf
python -m cr.config > /tmp/nginx-origins.conf
nginx -t -q -c /app/nginx.conf
(
  until python -c 'import socket; socket.create_connection(("127.0.0.1", 8001), 1).close()' 2>/dev/null; do
    sleep 1
  done
  exec nginx -c /app/nginx.conf
) &

jump="${CR_JUMP_DIR:-/data/jump}"
install -d -m 0755 -o cr "$jump"
install -d -m 0755 /run/sshd
[ -s "$jump/ssh_host_ed25519_key" ] || ssh-keygen -q -t ed25519 -N '' -C cr-jump -f "$jump/ssh_host_ed25519_key"
[ -e "$jump/authorized_keys" ] || install -m 0600 -o cr /dev/null "$jump/authorized_keys"
python -m sandbox.jump > /run/sshd-jump.conf
(/usr/sbin/sshd -t -f /run/sshd-jump.conf && exec /usr/sbin/sshd -D -e -f /run/sshd-jump.conf) &

gosu cr env TERMINAL_KEEP=1 ttyd -W -a -b /vm-terminal/attack -t disableResizeOverlay=true -t disableLeaveAlert=true -i 127.0.0.1 -p 7691 /app/vm-terminal.sh cr-kali attack &
gosu cr env TERMINAL_KEEP=1 ttyd -W -a -b /vm-terminal/defence -t disableResizeOverlay=true -t disableLeaveAlert=true -i 127.0.0.1 -p 7692 /app/vm-terminal.sh cr-waf defence &
gosu cr env TERMINAL_KEEP=1 ttyd -W -a -b /vm-terminal/ids -t disableResizeOverlay=true -t disableLeaveAlert=true -i 127.0.0.1 -p 7693 /app/vm-terminal.sh cr-infra ids &

exec gosu cr sh -c '
  if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
    [ -s /data/secret-key ] || (umask 077 && python -c "import secrets; print(secrets.token_urlsafe(50))" > /data/secret-key)
    DJANGO_SECRET_KEY="$(cat /data/secret-key)"
    export DJANGO_SECRET_KEY
  fi
  python manage.py migrate --noinput
  python manage.py vpn_relay &
  python manage.py register_pipeline &
  python -m sandbox.kibana &
  exec waitress-serve --listen=127.0.0.1:8001 --threads=16 \
    --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for \
    --clear-untrusted-proxy-headers cr.wsgi:application
'
