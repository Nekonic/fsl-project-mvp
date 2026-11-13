set -eu

verb=$1
wargame=$2
kept="${CR_PRISTINE:-/opt/cr/pristine}/$wargame"

compose() { docker compose -p "$wargame" -f "/opt/cr/wargames/$wargame.yaml" "$@"; }
volumes() {
  docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Destination}} {{.Source}}{{println}}{{end}}{{end}}' "$1"
}

case "$verb" in
  keep)
    compose up -d --wait --pull never
    compose stop --timeout 120
    rm -rf "$kept"
    for container in $(compose config --services); do
      volumes "$container" | while read -r path source; do
        [ -n "$path" ] || continue
        mkdir -p "$kept/$container$path"
        cp -a "$source/." "$kept/$container$path/"
      done
    done
    compose down -v --timeout 1
    ;;
  restore)
    for container in $(compose config --services); do
      [ "$(docker inspect --format '{{.State.Status}}' "$container")" = created ] || continue
      volumes "$container" | while read -r path source; do
        [ -n "$path" ] && [ -d "$kept/$container$path" ] || continue
        [ -z "$(ls -A "$source")" ] || continue
        cp -a "$kept/$container$path/." "$source/"
      done
    done
    ;;
  *)
    echo "pristine.sh keep|restore <wargame>" >&2
    exit 2
    ;;
esac
