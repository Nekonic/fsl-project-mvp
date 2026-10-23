#!/bin/bash
set -euo pipefail

rm -f /tmp/fsl-corp-ready
rm -f /var/www/html/wp-config.php

docker-entrypoint.sh apache2-foreground &
APACHE_PID=$!
trap 'kill -TERM "$APACHE_PID"' TERM INT

cd /var/www/html
for i in $(seq 1 60); do
  if wp db check --allow-root >/dev/null 2>&1; then break; fi
  sleep 2
done

if wp core is-installed --allow-root >/dev/null 2>&1; then
  wp user update admin --user_pass=corp-admin-pass --skip-email --allow-root
else
  wp core install --allow-root \
    --url="${FSL_WP_URL}" --title="Northwind Community" \
    --admin_user=admin --admin_password=corp-admin-pass \
    --admin_email=admin@corp.com --skip-email
  wp --allow-root --user=admin plugin activate ultimate-member
  wp --allow-root --user=admin plugin activate wp-gdpr-compliance
  wp --allow-root --user=admin plugin activate easy-post-submission
  wp option update users_can_register 0 --allow-root
  wp option update default_role subscriber --allow-root
  wp option patch update um_options account_tab_password 1 --allow-root >/dev/null 2>&1 || true
  wp --allow-root --user=admin eval 'UM()->setup()->install_default_forms(); UM()->setup()->install_default_pages();'
  wp --allow-root --user=admin eval-file /usr/local/bin/fsl-rbsm-form.php
fi
touch /tmp/fsl-corp-ready

wait "$APACHE_PID"
