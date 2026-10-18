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

generated() {
  file="$DATA/$1"
  [ -s "$file" ] || python -c 'import secrets; print(secrets.token_urlsafe(24))' > "$file"
  chmod 600 "$file"
  if [ -n "${gid:-}" ] && [ "$gid" != 0 ]; then
    chgrp "$gid" "$file"
    chmod 640 "$file"
  fi
  cat "$file"
}

[ -n "${FSL_GNS3_ADMIN_PASSWORD:-}" ] || FSL_GNS3_ADMIN_PASSWORD="$(generated admin-password)"
[ -n "${FSL_GNS3_AUDITOR_PASSWORD:-}" ] || FSL_GNS3_AUDITOR_PASSWORD="$(generated auditor-password)"
export FSL_GNS3_ADMIN_PASSWORD FSL_GNS3_AUDITOR_PASSWORD

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
