set -eu
before=$(sysctl -n kern.boottime | sed 's/.*sec = \([0-9]*\),.*/\1/')
install -m 0600 /tmp/cr-config.xml /conf/config.xml
mkdir -p /usr/local/etc/suricata/conf.d /usr/local/etc/suricata/rules
install -m 0644 /tmp/cr-suricata.yaml /usr/local/etc/suricata/conf.d/cr.yaml
install -m 0644 /tmp/cr.rules /usr/local/etc/suricata/rules/cr.rules
rm -f /tmp/cr-config.xml /tmp/cr-suricata.yaml /tmp/cr.rules
daemon -f sh -c 'sleep 3; /sbin/shutdown -r now'
echo "cr-edge booted $before"
echo "cr-edge rebooting"
