#!/bin/sh
set -eu

ACCOUNT=analyst
NGINX=/usr/sbin/nginx
SUDOERS=/etc/sudoers.d/analyst
SSHD=/etc/ssh/sshd_config.d/60-analyst.conf
FENCE=/etc/nftables.conf
READ_ONLY="/etc/nginx /var/log/nginx /var/log/modsecurity"

account_made() {
  id "$ACCOUNT" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$ACCOUNT"
  usermod --groups adm --password '*' "$ACCOUNT"
  chmod 0750 "/home/$ACCOUNT"
}

nginx_checks_allowed() {
  printf '%s ALL=(root) NOPASSWD: %s -t, %s -T\n' "$ACCOUNT" "$NGINX" "$NGINX" > "$SUDOERS.new"
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

no_network_for_the_account() {
  printf 'table inet analyst\ndelete table inet analyst\ntable inet analyst {\n  chain output {\n    type filter hook output priority filter; policy accept;\n    meta skuid %s drop\n  }\n}\n' \
    "$ACCOUNT" > "$FENCE"
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

account_made
nginx_checks_allowed
shell_only_over_ssh
no_network_for_the_account
nothing_writable_by_its_groups
