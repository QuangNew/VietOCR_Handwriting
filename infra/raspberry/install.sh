#!/bin/sh
# Install the already-built, reviewed bundle. No package downloads or firmware.
# Usage: sudo sh install.sh /home/admin/vietocr-v4 /home/admin/vietocr-v4-upload
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run installer with sudo' >&2; exit 1; }
bundle=$(realpath "$1")
config=$(realpath "$2")
test -x "$bundle/vietocr-gateway"
config_name=${3:-gateway.json}
case "$config_name" in gateway.json|gateway-test.json) ;; *) echo "Invalid config filename" >&2; exit 1;; esac
test -f "$config/$config_name"
id vietocr >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/vietocr --shell /usr/sbin/nologin --groups video,spi,gpio vietocr
install -d -o root -g vietocr -m 750 /opt/vietocr /etc/vietocr
install -o root -g root -m 755 "$bundle/vietocr-gateway" /opt/vietocr/vietocr-gateway.next
mv -f /opt/vietocr/vietocr-gateway.next /opt/vietocr/vietocr-gateway
install -o vietocr -g vietocr -m 600 "$config/ingress.token" /etc/vietocr/ingress.token
install -o vietocr -g vietocr -m 600 "$config/telemetry.token" /etc/vietocr/telemetry.token
install -o root -g vietocr -m 640 "$config/$config_name" /etc/vietocr/gateway.json
if [ ! -e /etc/vietocr/camera-desk.env ]; then
    install -o root -g vietocr -m 640 "$bundle/raspberry/camera-desk.env.example" /etc/vietocr/camera-desk.env
fi
install -o root -g root -m 644 "$bundle/raspberry/vietocr-gateway.service" /etc/systemd/system/vietocr-gateway.service
install -o root -g root -m 644 "$bundle/raspberry/vietocr-camera@.service" /etc/systemd/system/vietocr-camera@.service
runuser -u vietocr -- /opt/vietocr/vietocr-gateway /etc/vietocr/gateway.json --check-config
systemctl daemon-reload
systemctl enable --now vietocr-camera@desk.service vietocr-gateway.service
systemctl restart vietocr-camera@desk.service vietocr-gateway.service
systemctl is-active vietocr-camera@desk.service vietocr-gateway.service
