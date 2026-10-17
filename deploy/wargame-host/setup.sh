set -eu
cd "$(dirname "$0")"

APT="apt-get -y -o DPkg::Lock::Timeout=600"

export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components:.*/Components: main restricted universe/' \
  /etc/apt/sources.list.d/ubuntu.sources
$APT update
$APT install docker.io docker-compose-v2

install -d -m 0755 /etc/docker /opt/fsl/wargames
install -m 0644 daemon.json /etc/docker/daemon.json
systemctl enable docker
systemctl restart docker

for compose in wargames/*.yaml; do
  install -m 0644 "$compose" /opt/fsl/wargames/
  docker compose -f "/opt/fsl/wargames/${compose##*/}" config --quiet
  docker compose -f "/opt/fsl/wargames/${compose##*/}" pull --quiet
done

if [ -f loaded ]; then
  while read -r image id url; do
    curl -fsS --retry 5 --retry-all-errors -o /var/lib/fsl/loaded.tar "$url"
    docker load -q -i /var/lib/fsl/loaded.tar
    rm /var/lib/fsl/loaded.tar
    [ "$(docker image inspect --format '{{.Id}}' "$image")" = "$id" ]
  done < loaded
  docker image prune -f
fi

install -m 0644 ../suricata/suricata.yaml /opt/fsl/suricata.yaml
install -m 0644 sensor.yaml /opt/fsl/sensor.yaml
install -d -m 0755 /opt/fsl/rules
install -m 0644 ../suricata/rules/local.rules /opt/fsl/rules/local.rules
install -d -m 2750 -g adm /var/log/suricata
FSL_SENSOR_INTERFACE=lo docker compose -f /opt/fsl/sensor.yaml config --quiet
FSL_SENSOR_INTERFACE=lo docker compose -f /opt/fsl/sensor.yaml pull --quiet
