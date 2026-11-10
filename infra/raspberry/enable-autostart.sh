#!/bin/sh
# Reuse installed runtime/configuration. No token copies, downloads or reboot.
# Usage: sudo sh enable-autostart.sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo' >&2; exit 1; }
systemctl daemon-reload
for unit in vietocr-camera@desk.service vietocr-gateway.service vietocr-tunnel.service; do
    systemctl cat "$unit" >/dev/null
done
if systemctl cat NetworkManager.service >/dev/null 2>&1; then
    systemctl enable NetworkManager.service NetworkManager-wait-online.service
    # Only touch active Wi-Fi profiles, never print saved passwords or replace DNS.
    nmcli -t -f UUID,TYPE connection show --active | while IFS=: read -r profile kind; do
        [ "$kind" != '802-11-wireless' ] || nmcli connection modify uuid "$profile" connection.autoconnect yes
    done
fi
systemctl daemon-reload
systemctl reset-failed vietocr-camera@desk.service vietocr-gateway.service vietocr-tunnel.service
systemctl enable --now vietocr-camera@desk.service vietocr-gateway.service vietocr-tunnel.service
systemctl is-enabled vietocr-camera@desk.service vietocr-gateway.service vietocr-tunnel.service
systemctl is-active vietocr-camera@desk.service vietocr-gateway.service vietocr-tunnel.service
