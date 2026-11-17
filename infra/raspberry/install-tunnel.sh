#!/bin/sh
# Install a reviewed Pi connector config, never the account-management cert.pem.
# Usage: sudo sh install-tunnel.sh /home/admin/vietocr-tunnel-upload <Pi UUID>
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Use sudo' >&2; exit 1; }
[ "$#" -eq 2 ] || { echo 'Usage: install-tunnel.sh <staging-directory> <Pi tunnel UUID>' >&2; exit 1; }
stage=$(realpath "$1")
# A UUID read with sed from an existing CRLF YAML retains a trailing CR.
# Accept that line ending while still requiring a canonical UUID.
carriage_return=$(printf '\r')
uuid=${2%"$carriage_return"}
printf '%s\n' "$uuid" | LC_ALL=C grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || {
    echo 'Invalid UUID: expected the 36-character Pi tunnel ID from pi.yml.' >&2
    exit 1
}
test -x /usr/local/bin/cloudflared
test -f "$stage/pi.yml"
test -f "$stage/$uuid.json"
test ! -L "$stage/$uuid.json"
chmod 700 "$stage"
chmod 600 "$stage/pi.yml" "$stage/$uuid.json"
id cloudflared >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/cloudflared --shell /usr/sbin/nologin cloudflared
install -d -o root -g cloudflared -m 750 /etc/cloudflared
install -o cloudflared -g cloudflared -m 600 "$stage/$uuid.json" "/etc/cloudflared/$uuid.json"
# Normalize existing staging files too; the helper update only fixes new ones.
sed 's/\r$//' "$stage/pi.yml" > /etc/cloudflared/pi.yml.next
chown root:cloudflared /etc/cloudflared/pi.yml.next
chmod 640 /etc/cloudflared/pi.yml.next
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
