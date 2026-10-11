set -eu
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$BUNDLE/deploy/opnsense"
WORK=/var/lib/fsl-opnsense
APT="apt-get -y -o DPkg::Lock::Timeout=600"
. "$BUNDLE/fsl/opnsense.conf"

export DEBIAN_FRONTEND=noninteractive
$APT update
$APT install --no-install-recommends \
  ca-certificates curl bzip2 openssl coreutils fdisk python3 \
  qemu-utils qemu-system-x86 dosfstools mtools

rm -rf "$WORK"
mkdir -p "$WORK/seed/conf"
cd "$WORK"

curl -fsSLo "$NANO.bz2" "$MIRROR/$VERSION/$NANO.bz2"
curl -fsSLo "$NANO.sig" "$MIRROR/$VERSION/$NANO.sig"
curl -fsSLo release.pub "$MIRROR/$VERSION/OPNsense-$VERSION.pub"
echo "$IMAGE_SHA256  $NANO.bz2" | sha256sum -c -
test "$(openssl pkey -pubin -in release.pub -outform DER | sha256sum | cut -d' ' -f1)" = "$PUBKEY_SHA256"
bunzip2 -f "$NANO.bz2"
openssl base64 -d -in "$NANO.sig" -out image.sig
openssl dgst -sha256 -verify release.pub -signature image.sig "$NANO"

install -m 0600 "$BUNDLE/fsl/config.xml" seed/conf/config.xml
truncate -s 64M seed.img
echo 'start=2048, type=c' | sfdisk --quiet seed.img
mkfs.vfat --offset 2048 -n FSLSEED seed.img 64512
MTOOLS_SKIP_CHECK=1 mcopy -i seed.img@@1048576 -s seed/conf ::/

python3 "$HERE/importer.py" "$NANO" seed.img

qemu-img convert -f raw -O qcow2 -c "$NANO" opnsense.qcow2
{ read -r URL; read -r TOKEN; } < /var/lib/fsl/upload
curl -fsS -X PUT -H "X-Auth-Token: $TOKEN" -H "Content-Type: application/octet-stream" \
  --upload-file opnsense.qcow2 "$URL"
cd /
rm -rf "$WORK"
