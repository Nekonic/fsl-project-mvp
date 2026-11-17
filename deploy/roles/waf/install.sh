#!/bin/sh
set -eu
cd "$(dirname "$0")"

MODSECURITY=3.0.16
MODSECURITY_SHA256=739be3c71b1939f14e91afe1eeae654acbd440da11bd29790458840bc315b4c0
CONNECTOR=1.0.4
CONNECTOR_SHA256=6bdc7570911be884c1e43aaf85046137f9fde0cfa0dd4a55b853c81c45a13313
NGINX=1.24.0
NGINX_SHA256=77a2541637b92a621e3ee76776c8b7b40cf6d707e69ba53a940283e30ff2f55d
CRS=4.25.1
CRS_SHA256=e314bc5b64a268ae4264822bc93db24eb93c5eb648ff80aed96b23f3fce2c701
RELEASES=https://github.com/owasp-modsecurity
CRS_RELEASES=https://github.com/coreruleset/coreruleset/releases/download

BUILD=/var/tmp/waf-build
BUILT=/var/lib/waf-build/modsecurity-$MODSECURITY-connector-$CONNECTOR-nginx-$NGINX-crs-$CRS
MODSEC_DIR=/etc/nginx/modsecurity
EXCLUSIONS=$MODSEC_DIR/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf
AUDIT_LOG=/var/log/modsecurity/audit/audit.log
REFUSED_LOG=/var/log/nginx/refused.log
SHARE=/usr/local/share/slot

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -y -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold"

installed() {
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    $APT update || :
    $APT install "$@" && return 0
    [ "$attempt" -lt 10 ] || return 1
    sleep 15
  done
}

ubuntu_trimmed() {
  sed -i -e 's/^Components:.*/Components: main restricted universe/' -e 's#^URIs:.*#URIs: http://mirror.kakao.com/ubuntu/#' /etc/apt/sources.list.d/ubuntu.sources
  $APT purge snapd modemmanager
  printf 'Package: snapd modemmanager\nPin: release *\nPin-Priority: -1\n' > /etc/apt/preferences.d/no-snapd-modemmanager
}

fetched() {
  curl -fsSLo "$BUILD/$1" "$2"
  echo "$3  $BUILD/$1" | sha256sum -c -
  tar -xzf "$BUILD/$1" -C "$BUILD"
}

modsecurity_built() {
  rm -rf "$BUILD"
  mkdir -p "$BUILD"
  fetched modsecurity.tar.gz "$RELEASES/ModSecurity/releases/download/v$MODSECURITY/modsecurity-v$MODSECURITY.tar.gz" "$MODSECURITY_SHA256"
  fetched connector.tar.gz "$RELEASES/ModSecurity-nginx/releases/download/v$CONNECTOR/ModSecurity-nginx-v$CONNECTOR.tar.gz" "$CONNECTOR_SHA256"
  fetched nginx.tar.gz "https://nginx.org/download/nginx-$NGINX.tar.gz" "$NGINX_SHA256"
  fetched crs.tar.gz "$CRS_RELEASES/v$CRS/coreruleset-$CRS-minimal.tar.gz" "$CRS_SHA256"
  (
    cd "$BUILD/modsecurity-v$MODSECURITY"
    ./configure --prefix=/usr/local/modsecurity --disable-doxygen-doc --disable-examples
    make -j"$(nproc)"
    make install
  )
  echo /usr/local/modsecurity/lib > /etc/ld.so.conf.d/modsecurity.conf
  ldconfig
  (
    cd "$BUILD/nginx-$NGINX"
    MODSECURITY_INC=/usr/local/modsecurity/include MODSECURITY_LIB=/usr/local/modsecurity/lib \
      ./configure --with-compat --add-dynamic-module="$BUILD/ModSecurity-nginx-v$CONNECTOR"
    make modules
    install -D -m 644 objs/ngx_http_modsecurity_module.so /usr/lib/nginx/modules/ngx_http_modsecurity_module.so
  )
  install -d "$MODSEC_DIR"
  rm -rf "$MODSEC_DIR/crs"
  mv "$BUILD/coreruleset-$CRS" "$MODSEC_DIR/crs"
  cp "$MODSEC_DIR/crs/crs-setup.conf.example" "$MODSEC_DIR/crs/crs-setup.conf"
  install -m 644 "$BUILD/modsecurity-v$MODSECURITY/unicode.mapping" "$MODSEC_DIR/unicode.mapping"
  rm -rf "$BUILD"
  install -d "$(dirname "$BUILT")"
  touch "$BUILT"
}

upstreams_named() {
  sed -i -e '/[[:space:]]board$/d' -e '/[[:space:]]corp-wp$/d' /etc/hosts
  printf '%s board\n%s corp-wp\n' "$1" "$2" >> /etc/hosts
}

rsyslog_may_read_the_waf_logs() {
  grep -qxF 'global(maxMessageSize="64k")' /etc/rsyslog.conf || sed -i '1i global(maxMessageSize="64k")' /etc/rsyslog.conf
  [ -f /etc/apparmor.d/usr.sbin.rsyslogd ] || return 0
  install -d /etc/apparmor.d/local
  printf '%s r,\n%s r,\n' "$AUDIT_LOG" "$REFUSED_LOG" > /etc/apparmor.d/local/usr.sbin.rsyslogd
  systemctl reload apparmor
}

logs_emptied() {
  install -m 0644 -o www-data -g adm /dev/null "$AUDIT_LOG"
  install -m 0644 -o www-data -g adm /dev/null "$REFUSED_LOG"
}

sealed_for_snapshot() {
  cloud-init clean --logs
  : > /etc/machine-id
}

ubuntu_trimmed
installed ca-certificates curl iproute2 nano less nginx rsyslog build-essential pkg-config libpcre2-dev zlib1g-dev libxml2-dev \
  libyajl-dev libcurl4-openssl-dev liblmdb-dev libmaxminddb-dev
nginx -V 2>&1 | grep -q "nginx/$NGINX "
nginx -V 2>&1 | grep -q -- "--with-compat"

[ -f "$BUILT" ] || modsecurity_built
echo "load_module /usr/lib/nginx/modules/ngx_http_modsecurity_module.so;" > /etc/nginx/modules-enabled/50-mod-http-modsecurity.conf
[ -f "$EXCLUSIONS" ] || install -m 664 -g adm /dev/null "$EXCLUSIONS"

install -m 0644 modsecurity.conf "$MODSEC_DIR/modsecurity.conf"
install -m 0644 board.com.conf /etc/nginx/conf.d/board.com.conf
rm -f /etc/nginx/sites-enabled/default
install -d -o www-data -g adm -m 750 /var/log/modsecurity /var/log/modsecurity/audit
install -d -o www-data -m 700 /var/cache/modsecurity
upstreams_named 127.0.0.1 127.0.0.1

install -d -m 0755 "$SHARE"
install -m 0644 log-shipper.conf "$SHARE/log-shipper.conf"
install -m 0755 slot-boot /usr/local/sbin/slot-boot
install -m 0644 slot-boot.service /etc/systemd/system/slot-boot.service
rsyslog_may_read_the_waf_logs

logs_emptied
nginx -t
systemctl daemon-reload
systemctl enable nginx.service rsyslog.service slot-boot.service
systemctl restart nginx.service
systemctl stop nginx.service
logs_emptied

sealed_for_snapshot
