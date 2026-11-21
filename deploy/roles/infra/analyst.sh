#!/bin/sh
set -eu

ACCOUNT=analyst
SURICATA=/usr/local/bin/suricata
SURICATASC=/usr/local/bin/suricatasc
SUDOERS=/etc/sudoers.d/analyst
SSHD=/etc/ssh/sshd_config.d/60-analyst.conf
FENCE=/etc/nftables.conf
SNAPSHOT_DIR=/var/lib/cr-reloaded
RULE_FILE=/var/lib/suricata/rules/local.rules
READ_ONLY="/etc/suricata /var/lib/suricata /var/log/suricata /etc/rsyslog.conf /etc/rsyslog.d"
CLOSED="/usr/local/share/slot /var/lib/cr-ruletest"

account_made() {
  id "$ACCOUNT" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$ACCOUNT"
  usermod --groups adm --password '*' "$ACCOUNT"
  chmod 0750 "/home/$ACCOUNT"
}

sensor_checks_allowed() {
  printf '%s ALL=(root) NOPASSWD: %s -T, %s -c reload-rules\n' "$ACCOUNT" "$SURICATA" "$SURICATASC" > "$SUDOERS.new"
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
  printf 'table inet analyst\ndelete table inet analyst\ntable inet analyst {\n  chain output {\n    type filter hook output priority filter; policy accept;\n    meta skuid %s oif "lo" ip daddr 127.0.0.0/8 accept\n    meta skuid %s oif "lo" ip6 daddr ::1 accept\n    meta skuid %s drop\n  }\n}\n' \
    "$ACCOUNT" "$ACCOUNT" "$ACCOUNT" > "$FENCE"
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

router_and_customers_closed() {
  for tree in $CLOSED; do
    [ -e "$tree" ] || continue
    chown root:root "$tree"
    chmod 0700 "$tree"
  done
}

rule_file_writable() {
  [ -f "$RULE_FILE" ] || install -m 0644 /dev/null "$RULE_FILE"
  chown root:root "$RULE_FILE"
  chmod 0644 "$RULE_FILE"
  setfacl -m "u:$ACCOUNT:rw" "$RULE_FILE"
}

reload_snapshot_closed() {
  install -d -m 0700 -o root -g root "$SNAPSHOT_DIR"
  chown root:root "$SNAPSHOT_DIR"
  chmod 0700 "$SNAPSHOT_DIR"
}

account_made
sensor_checks_allowed
shell_only_over_ssh
only_loopback_for_the_account
nothing_writable_by_its_groups
router_and_customers_closed
rule_file_writable
reload_snapshot_closed
