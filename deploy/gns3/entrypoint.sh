#!/bin/sh
set -eu

DATA="${FSL_GNS3_DATA:-/var/lib/fsl-gns3}"
HERE=/opt/fsl-gns3
export FSL_GNS3_DATA="$DATA"
mkdir -p "$DATA/projects" "$DATA/resources"

SOCK=/var/run/docker.sock
if [ -S "$SOCK" ]; then
  gid=$(stat -c %g "$SOCK")
  if [ "$gid" != 0 ] && ! getent group "$gid" >/dev/null; then
    groupadd -g "$gid" dockersock
  fi
  group=$(getent group "$gid" | cut -d: -f1)
  if [ -n "$group" ] && ! id -nG gns3 | tr ' ' '\n' | grep -qx "$group"; then
    usermod -aG "$group" gns3
  fi
fi

if [ -z "${FSL_GNS3_ADMIN_PASSWORD:-}" ]; then
  [ -s "$DATA/admin-password" ] || python -c 'import secrets; print(secrets.token_urlsafe(24))' > "$DATA/admin-password"
  chmod 600 "$DATA/admin-password"
  if [ -n "${gid:-}" ] && [ "$gid" != 0 ]; then
    chgrp "$gid" "$DATA/admin-password"
    chmod 640 "$DATA/admin-password"
  fi
  FSL_GNS3_ADMIN_PASSWORD="$(cat "$DATA/admin-password")"
fi
export FSL_GNS3_ADMIN_PASSWORD

cat > "$DATA/gns3_server.conf" <<CONF
[Server]
host = 0.0.0.0
port = 3080
projects_path = $DATA/projects
resources_path = $DATA/resources
images_path = $DATA/images
appliances_path = $DATA/appliances
symbols_path = $DATA/symbols
configs_path = $DATA/configs
report_errors = False

[Controller]
default_admin_username = admin
default_admin_password = $FSL_GNS3_ADMIN_PASSWORD
CONF
chmod 600 "$DATA/gns3_server.conf"

python "$HERE/provision.py" bootstrap
chown -R gns3 "$DATA"
exec gosu gns3 sh -c '
  gns3server --config "$FSL_GNS3_DATA/gns3_server.conf" &
  server=$!
  python /opt/fsl-gns3/provision.py provision || echo "fsl-gns3: provisioning failed; the server keeps running" >&2
  wait "$server"
'
