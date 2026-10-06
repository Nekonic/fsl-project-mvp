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

write_pf() {
  if [ -n "$3" ]; then
    printf 'map $host $pf_upstream { default "%s"; }\nmap $host $pf_host { default "%s"; }\nmap $host $pf_cookie { default "PHPSESSID=%s"; }\n' "$1" "$2" "$3" > /tmp/pf-resolved.conf
  else
    printf 'map $host $pf_upstream { default ""; }\nmap $host $pf_host { default ""; }\nmap $host $pf_cookie { default ""; }\n' > /tmp/pf-resolved.conf
  fi
}

CUR=""
prime_pf() {
  out=$(cd /app && gosu fsl python pf_prime.py ${CUR:+--check "$CUR"} 2>/dev/null) || return 1
  [ -n "$out" ] || return 1
  write_pf $out
  CUR=$(printf '%s' "$out" | cut -d' ' -f3)
}

write_pf

nginx -c /app/nginx.conf

(
  while :; do
    prime_pf && nginx -s reload -c /app/nginx.conf 2>/dev/null || true
    sleep 900
  done
) &

gosu fsl ttyd -W -b /vm-terminal/fsl-kali -i 127.0.0.1 -p 7691 /app/vm-terminal.sh fsl-kali &
gosu fsl ttyd -W -b /vm-terminal/fsl-waf -i 127.0.0.1 -p 7692 /app/vm-terminal.sh fsl-waf &

exec gosu fsl sh -c '
  python manage.py migrate --noinput
  python register_pipeline.py
  exec waitress-serve --listen=127.0.0.1:8001 --threads=8 \
    --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-for \
    --clear-untrusted-proxy-headers fsl.wsgi:application
'
