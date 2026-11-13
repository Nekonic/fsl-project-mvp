set -eu
cd "$(dirname "$0")"

APT="apt-get -y -o DPkg::Lock::Timeout=600"

export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components:.*/Components: main restricted universe/' \
  /etc/apt/sources.list.d/ubuntu.sources
$APT update
$APT purge snapd modemmanager
printf 'Package: snapd modemmanager\nPin: release *\nPin-Priority: -1\n' > /etc/apt/preferences.d/no-snapd-modemmanager
$APT install docker.io docker-compose-v2

install -d -m 0755 /etc/docker /opt/cr/wargames
install -m 0644 daemon.json /etc/docker/daemon.json
systemctl enable docker
systemctl restart docker

for compose in wargames/*.yaml; do
  install -m 0644 "$compose" /opt/cr/wargames/
  docker compose -f "/opt/cr/wargames/${compose##*/}" config --quiet
  docker compose -f "/opt/cr/wargames/${compose##*/}" pull --quiet
done

if [ -f loaded ]; then
  install -d -m 0700 /var/lib/cr
  served=$(cat served-from)
  while read -r image id name; do
    curl -fsS --retry 5 --retry-all-errors -H "Host: localhost" -o /var/lib/cr/loaded.tar "$served$name/"
    docker load -q -i /var/lib/cr/loaded.tar
    rm /var/lib/cr/loaded.tar
    [ "$(docker image inspect --format '{{.Id}}' "$image")" = "$id" ]
  done < loaded
  docker image prune -f
fi

install -m 0644 ../suricata/suricata.yaml /opt/cr/suricata.yaml
install -m 0644 sensor.yaml /opt/cr/sensor.yaml
install -d -m 0755 /opt/cr/rules
install -m 0644 ../suricata/rules/local.rules /opt/cr/rules/local.rules
install -d -m 2750 -g adm /var/log/suricata
CR_SENSOR_INTERFACE=lo docker compose -f /opt/cr/sensor.yaml config --quiet
CR_SENSOR_INTERFACE=lo docker compose -f /opt/cr/sensor.yaml pull --quiet

install -m 0755 pristine.sh /opt/cr/pristine.sh
keeping=""
for compose in wargames/*.yaml; do
  wargame=${compose##*/}
  sh /opt/cr/pristine.sh keep "${wargame%.yaml}" &
  keeping="$keeping $!"
done
for job in $keeping; do wait "$job"; done
