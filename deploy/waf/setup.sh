set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$(mktemp -d)"

MODSECURITY=3.0.16
MODSECURITY_SHA256=739be3c71b1939f14e91afe1eeae654acbd440da11bd29790458840bc315b4c0
CONNECTOR=1.0.4
CONNECTOR_SHA256=6bdc7570911be884c1e43aaf85046137f9fde0cfa0dd4a55b853c81c45a13313
NGINX=1.24.0
NGINX_SHA256=77a2541637b92a621e3ee76776c8b7b40cf6d707e69ba53a940283e30ff2f55d
CRS=4.25.1
CRS_SHA256=e314bc5b64a268ae4264822bc93db24eb93c5eb648ff80aed96b23f3fce2c701
APT="apt-get -y -o DPkg::Lock::Timeout=600"

fetch() {
  curl -fsSLo "$BUILD/$1" "$2"
  echo "$3  $BUILD/$1" | sha256sum -c -
  tar -xzf "$BUILD/$1" -C "$BUILD"
}

export DEBIAN_FRONTEND=noninteractive
$APT update
$APT install nginx build-essential pkg-config libpcre2-dev zlib1g-dev libxml2-dev \
  libyajl-dev libcurl4-openssl-dev liblmdb-dev libmaxminddb-dev
nginx -V 2>&1 | grep -q "nginx/$NGINX "
nginx -V 2>&1 | grep -q -- "--with-compat"

fetch modsecurity.tar.gz \
  "https://github.com/owasp-modsecurity/ModSecurity/releases/download/v$MODSECURITY/modsecurity-v$MODSECURITY.tar.gz" \
  "$MODSECURITY_SHA256"
fetch connector.tar.gz \
  "https://github.com/owasp-modsecurity/ModSecurity-nginx/releases/download/v$CONNECTOR/ModSecurity-nginx-v$CONNECTOR.tar.gz" \
  "$CONNECTOR_SHA256"
fetch nginx.tar.gz "https://nginx.org/download/nginx-$NGINX.tar.gz" "$NGINX_SHA256"
fetch crs.tar.gz \
  "https://github.com/coreruleset/coreruleset/releases/download/v$CRS/coreruleset-$CRS-minimal.tar.gz" \
  "$CRS_SHA256"

cd "$BUILD/modsecurity-v$MODSECURITY"
./configure --prefix=/usr/local/modsecurity --disable-doxygen-doc --disable-examples
make -j"$(nproc)"
make install
echo /usr/local/modsecurity/lib > /etc/ld.so.conf.d/modsecurity.conf
ldconfig

cd "$BUILD/nginx-$NGINX"
MODSECURITY_INC=/usr/local/modsecurity/include MODSECURITY_LIB=/usr/local/modsecurity/lib \
  ./configure --with-compat --add-dynamic-module="$BUILD/ModSecurity-nginx-v$CONNECTOR"
make modules
install -D -m 644 objs/ngx_http_modsecurity_module.so /usr/lib/nginx/modules/ngx_http_modsecurity_module.so
echo "load_module /usr/lib/nginx/modules/ngx_http_modsecurity_module.so;" \
  > /etc/nginx/modules-enabled/50-mod-http-modsecurity.conf

install -d /etc/nginx/modsecurity
mv "$BUILD/coreruleset-$CRS" /etc/nginx/modsecurity/crs
cp /etc/nginx/modsecurity/crs/crs-setup.conf.example /etc/nginx/modsecurity/crs/crs-setup.conf
install -m 644 "$BUILD/modsecurity-v$MODSECURITY/unicode.mapping" /etc/nginx/modsecurity/unicode.mapping
install -m 644 "$HERE/modsecurity.conf" /etc/nginx/modsecurity/modsecurity.conf
install -m 644 "$HERE/range.conf" /etc/nginx/conf.d/range.conf
rm -f /etc/nginx/sites-enabled/default
install -d -o www-data -g adm -m 750 /var/log/modsecurity /var/log/modsecurity/audit
install -d -o www-data -m 700 /var/cache/modsecurity
rm -rf "$BUILD"

cp /etc/hosts /tmp/hosts
echo "127.0.0.1 board" >> /etc/hosts
nginx -t
cp /tmp/hosts /etc/hosts
systemctl enable nginx
