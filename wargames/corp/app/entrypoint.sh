#!/bin/bash
set -euo pipefail

docker-entrypoint.sh apache2-foreground &
APACHE_PID=$!

cd /var/www/html
for i in $(seq 1 60); do
  if wp core is-installed --allow-root >/dev/null 2>&1; then break; fi
  if ! wp db check --allow-root >/dev/null 2>&1; then sleep 2; continue; fi
  wp core install --allow-root \
    --url="${FSL_WP_URL}" --title="Northwind Community" \
    --admin_user=admin --admin_password=corp-admin-pass \
    --admin_email=admin@corp.com --skip-email && break
  sleep 2
done

wp plugin activate ultimate-member --allow-root
wp plugin activate wp-gdpr-compliance --allow-root
wp plugin activate easy-post-submission --allow-root
wp option update users_can_register 0 --allow-root
wp option update default_role subscriber --allow-root
wp option patch update um_options account_tab_password 1 --allow-root >/dev/null 2>&1 || true
wp eval 'UM()->options()->update("registration_status","approved");' --allow-root >/dev/null 2>&1 || true

wait "$APACHE_PID"
