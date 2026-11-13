set -eu
cd "$(dirname "$0")"

APT="apt-get -y -o DPkg::Lock::Timeout=600"
BASE=/opt/cr
KEPT=$BASE/pristine

export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components:.*/Components: main restricted universe/' /etc/apt/sources.list.d/ubuntu.sources
$APT update
$APT purge snapd modemmanager
printf 'Package: snapd modemmanager\nPin: release *\nPin-Priority: -1\n' > /etc/apt/preferences.d/no-snapd-modemmanager
$APT install docker.io docker-compose-v2 ethtool rsyslog acl

printf 'fs.inotify.max_user_instances = 1024\nfs.inotify.max_user_watches = 524288\n' > /etc/sysctl.d/90-cr-range.conf
sysctl --system >/dev/null
printf 'MaxSessions 256\nMaxStartups 64:30:256\n' > /etc/ssh/sshd_config.d/60-cr.conf
sshd -t
systemctl reload ssh

install -d -m 0755 /etc/docker "$BASE" "$KEPT"
install -m 0644 daemon.json /etc/docker/daemon.json
systemctl enable docker
systemctl restart docker

install -m 0644 wargames.txt "$BASE/wargames.txt"
install -m 0644 pristine.yaml "$BASE/pristine.yaml"

while read -r image; do
  for attempt in 1 2 3 4 5; do
    docker pull -q "$image" && break
    [ "$attempt" = 5 ] && exit 1
    sleep 10
  done
done < images.txt

pristine() { docker compose -p pristine -f "$BASE/pristine.yaml" "$@"; }
pristine up -d --wait --wait-timeout 900 --pull never
pristine stop --timeout 120
for service in $(cat wargames.txt); do
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}} {{.Source}}{{println}}{{end}}{{end}}' \
    "pristine-$service" | while read -r path source; do
    [ -n "$path" ] || continue
    mkdir -p "$KEPT/$service$path"
    cp -a "$source/." "$KEPT/$service$path/"
  done
done
pristine down -v --timeout 1

printf 'global(maxMessageSize="64k")\nmodule(load="imfile")\n' > /etc/rsyslog.d/50-cr.conf
systemctl restart rsyslog
