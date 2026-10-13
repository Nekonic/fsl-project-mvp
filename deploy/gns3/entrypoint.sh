#!/bin/sh
set -eu

DATA=/data
HERE=/opt/fsl-gns3
mkdir -p "$DATA/projects"

if [ -z "${FSL_GNS3_ADMIN_PASSWORD:-}" ]; then
  [ -s "$DATA/admin-password" ] || python -c 'import secrets; print(secrets.token_urlsafe(24))' > "$DATA/admin-password"
  chmod 600 "$DATA/admin-password"
  FSL_GNS3_ADMIN_PASSWORD="$(cat "$DATA/admin-password")"
fi
export FSL_GNS3_ADMIN_PASSWORD

cat > "$DATA/gns3_server.conf" <<CONF
[Server]
host = 0.0.0.0
port = 3080
projects_path = $DATA/projects
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

for project in /topology/*.gns3; do
  name="$(basename "$project" .gns3)"
  mkdir -p "$DATA/projects/$name"
  rm -f "$DATA/projects/$name/$name.gns3".backup*
  cp "$project" "$DATA/projects/$name/$name.gns3"
done

python "$HERE/provision.py" bootstrap
gns3server --config "$DATA/gns3_server.conf" &
server=$!
python "$HERE/provision.py" provision || echo "fsl-gns3: provisioning failed; the server keeps running" >&2
wait "$server"
