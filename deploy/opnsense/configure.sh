set -eu
before=$(sysctl -n kern.boottime | sed 's/.*sec = \([0-9]*\),.*/\1/')
install -m 0600 /tmp/fsl-config.xml /conf/config.xml
mkdir -p /usr/local/etc/suricata/conf.d /usr/local/etc/suricata/rules
install -m 0644 /tmp/fsl-suricata.yaml /usr/local/etc/suricata/conf.d/fsl.yaml
install -m 0644 /tmp/fsl.rules /usr/local/etc/suricata/rules/fsl.rules
rm -f /tmp/fsl-config.xml /tmp/fsl-suricata.yaml /tmp/fsl.rules
daemon -f sh -c 'sleep 3; /sbin/shutdown -r now'
echo "fsl-edge booted $before"
echo "fsl-edge rebooting"
