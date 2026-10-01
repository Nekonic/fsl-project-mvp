set -eu
cd "$(dirname "$0")"

APT="apt-get -y -o DPkg::Lock::Timeout=600"
export DEBIAN_FRONTEND=noninteractive
$APT update
$APT install nginx

rm -f /etc/nginx/sites-enabled/default
install -m 644 nginx.conf /etc/nginx/conf.d/wiki.conf
rm -rf /usr/share/nginx/html
cp -r site /usr/share/nginx/html
nginx -t
systemctl enable nginx
