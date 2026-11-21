#!/bin/sh
set -eu

ACCOUNT=analyst
NGINX=/usr/local/sbin/nginx
SYSTEMCTL=/usr/bin/systemctl
SUDOERS=/etc/sudoers.d/analyst
SSHD=/etc/ssh/sshd_config.d/60-analyst.conf
FENCE=/etc/nftables.conf
SNAPSHOT_DIR=/var/lib/cr-reloaded
READ_ONLY="/etc/nginx /var/log/nginx /var/log/modsecurity /etc/rsyslog.conf /etc/rsyslog.d /usr/local/share/slot"
CRS=/etc/nginx/modsecurity/crs
DEFENCE_FILES="$CRS/crs-setup.conf $CRS/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf $CRS/rules/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf /etc/nginx/defence/http.conf /etc/nginx/defence/board.com.conf /etc/nginx/defence/corp.com.conf"

account_made() {
  id "$ACCOUNT" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$ACCOUNT"
  usermod --groups adm --password '*' "$ACCOUNT"
  chmod 0750 "/home/$ACCOUNT"
}

nginx_checks_allowed() {
  printf '%s ALL=(root) NOPASSWD: %s -t, %s -T, %s -s reload, %s reload nginx\n' "$ACCOUNT" "$NGINX" "$NGINX" "$NGINX" "$SYSTEMCTL" > "$SUDOERS.new"
  chmod 0440 "$SUDOERS.new"
  visudo -cf "$SUDOERS.new"
  mv "$SUDOERS.new" "$SUDOERS"
}

shell_only_over_ssh() {
  printf 'Match User %s\n    AllowTcpForwarding no\n    AllowStreamLocalForwarding no\n    AllowAgentForwarding no\n    X11Forwarding no\n    PermitTunnel no\n    PermitUserRC no\n' \
    "$ACCOUNT" > "$SSHD"
  chmod 0644 "$SSHD"
  sshd -t
}

only_loopback_for_the_account() {
  printf 'table inet analyst\ndelete table inet analyst\ntable inet analyst {\n  chain output {\n    type filter hook output priority filter; policy accept;\n    meta skuid %s oif "lo" accept\n    meta skuid %s drop\n  }\n}\n' \
    "$ACCOUNT" "$ACCOUNT" > "$FENCE"
  chmod 0644 "$FENCE"
  nft -c -f "$FENCE"
  systemctl enable nftables.service
}

nothing_writable_by_its_groups() {
  for tree in $READ_ONLY; do
    [ -e "$tree" ] || continue
    find "$tree" -xdev \( -group adm -o -group "$ACCOUNT" \) -perm -g+w -exec chmod g-w {} +
    find "$tree" -xdev -perm -o+w ! -type l -exec chmod o-w {} +
  done
}

defence_files_writable() {
  for file in $DEFENCE_FILES; do
    [ -f "$file" ] || install -m 0644 /dev/null "$file"
    chown root:"$ACCOUNT" "$file"
    chmod 0664 "$file"
  done
}

reload_snapshot_closed() {
  install -d -m 0700 -o root -g root "$SNAPSHOT_DIR"
  chown root:root "$SNAPSHOT_DIR"
  chmod 0700 "$SNAPSHOT_DIR"
}

account_made
nginx_checks_allowed
shell_only_over_ssh
only_loopback_for_the_account
nothing_writable_by_its_groups
defence_files_writable
reload_snapshot_closed
