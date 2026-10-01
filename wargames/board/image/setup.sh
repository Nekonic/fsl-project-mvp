set -eu
cd "$(dirname "$0")"

APT="apt-get -y -o DPkg::Lock::Timeout=600"
export DEBIAN_FRONTEND=noninteractive
$APT update
$APT install mysql-server python3-venv python3-dev default-libmysqlclient-dev build-essential pkg-config

mysql <<SQL
CREATE DATABASE IF NOT EXISTS board CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'board'@'localhost' IDENTIFIED BY 'board';
GRANT ALL ON board.* TO 'board'@'localhost';
SQL

useradd --system --home-dir /opt/board --shell /usr/sbin/nologin board
cp -r ../app /opt/board
python3 -m venv /opt/board/venv
/opt/board/venv/bin/pip install --no-cache-dir -r /opt/board/requirements.txt
install -d /opt/board/posts/static/vendor
curl -fsSLo /opt/board/posts/static/vendor/bootstrap.min.css \
  https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css
chmod +x /opt/board/entrypoint.sh
chown -R board: /opt/board
install -m 644 board.service /etc/systemd/system/board.service
systemctl enable board
