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
$APT install docker.io docker-compose-v2 ethtool bzip2 curl

printf 'fs.inotify.max_user_instances = 1024\nfs.inotify.max_user_watches = 524288\n' > /etc/sysctl.d/90-cr-range.conf
sysctl --system >/dev/null
printf 'MaxSessions 256\nMaxStartups 64:30:256\n' > /etc/ssh/sshd_config.d/60-cr.conf
sshd -t
systemctl reload ssh

GVISOR=https://storage.googleapis.com/gvisor/releases/release/20261026.0/x86_64/gvisor.tar.bz2
GVISOR_SHA512=26e4a327565f5da0f73261a6387e2c20f4695a232e330095a3111b70efd604fdf09d734e8cc8f714dbb5c5607ce8c87ea80b26df549d83a146f2efd5a1af448a
curl -fsSL --retry 5 -o /tmp/gvisor.tar.bz2 "$GVISOR"
echo "$GVISOR_SHA512  /tmp/gvisor.tar.bz2" | sha512sum -c -
tar -xjf /tmp/gvisor.tar.bz2 -C /usr/local/bin runsc containerd-shim-runsc-v1 gvisor-bin
rm /tmp/gvisor.tar.bz2

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
