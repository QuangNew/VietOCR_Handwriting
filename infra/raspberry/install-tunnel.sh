#!/bin/sh
# Install a reviewed Pi connector config, never the account-management cert.pem.
# Usage: sudo sh install-tunnel.sh /home/admin/vietocr-tunnel-upload <Pi UUID>
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Use sudo' >&2; exit 1; }
stage=$(realpath "$1")
uuid=$2
case "$uuid" in *[!0-9a-f-]*|'') echo 'Invalid UUID' >&2; exit 1;; esac
[ "${#uuid}" -eq 36 ] || { echo 'Invalid UUID length' >&2; exit 1; }
test -x /usr/local/bin/cloudflared
test -f "$stage/pi.yml"
test -f "$stage/$uuid.json"
test ! -L "$stage/$uuid.json"
chmod 700 "$stage"
chmod 600 "$stage/pi.yml" "$stage/$uuid.json"
id cloudflared >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/cloudflared --shell /usr/sbin/nologin cloudflared
install -d -o root -g cloudflared -m 750 /etc/cloudflared
install -o cloudflared -g cloudflared -m 600 "$stage/$uuid.json" "/etc/cloudflared/$uuid.json"
install -o root -g cloudflared -m 640 "$stage/pi.yml" /etc/cloudflared/pi.yml.next
runuser -u cloudflared -- /usr/local/bin/cloudflared --config /etc/cloudflared/pi.yml.next tunnel ingress validate
mv -f /etc/cloudflared/pi.yml.next /etc/cloudflared/pi.yml
script_dir=$(dirname "$(realpath "$0")")
install -o root -g root -m 644 "$script_dir/vietocr-tunnel.service" /etc/systemd/system/vietocr-tunnel.service
systemctl daemon-reload
systemctl enable --now vietocr-tunnel.service
systemctl restart vietocr-tunnel.service
systemctl is-active vietocr-tunnel.service
rm -- "$stage/$uuid.json"
echo 'Pi connector installed. Check HTTPS externally before switching compute origins.'
