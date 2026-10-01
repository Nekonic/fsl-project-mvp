set -eu
cd "$(dirname "$0")"

NODE=24.19.0
NODE_SHA256=14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647
SHOP=20.2.0
SHOP_SHA256=dbb457f74e908e28c41d7787e36d30d121d5b9f6178524720567b4aeb41f2968

curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v$NODE/node-v$NODE-linux-x64.tar.xz"
echo "$NODE_SHA256  /tmp/node.tar.xz" | sha256sum -c -
curl -fsSLo /tmp/shop.tgz \
  "https://github.com/juice-shop/juice-shop/releases/download/v$SHOP/juice-shop-${SHOP}_node24_linux_x64.tgz"
echo "$SHOP_SHA256  /tmp/shop.tgz" | sha256sum -c -

install -d /opt/node /opt/juice-shop
tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1
tar -xzf /tmp/shop.tgz -C /opt/juice-shop --strip-components=1
rm /tmp/node.tar.xz /tmp/shop.tgz

useradd --system --home-dir /opt/juice-shop --shell /usr/sbin/nologin juice
chown -R juice: /opt/juice-shop
install -m 644 juice-shop.service /etc/systemd/system/juice-shop.service
systemctl enable juice-shop
