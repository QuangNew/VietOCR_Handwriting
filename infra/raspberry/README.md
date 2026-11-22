# Triển khai Raspberry

Máy đã kiểm: Pi4B4GB `rasp4gb`, Raspberry Pi OS aarch64 / Debian13.7, µStreamer5.4, webcam `/dev/video0` native MJPEG1920×1080@30. Không cài Rust compiler lên Pi.

## Đường dẫn đã cài

- `/opt/vietocr/vietocr-gateway`: binary ARM64 từ CI.
- `/etc/vietocr/gateway.json`: cấu hình runtime, root:vietocr0640.
- `/etc/vietocr/ingress.token`, `/etc/vietocr/telemetry.token`: credential máy riêng,0600.
- `/etc/vietocr/camera-desk.env`: camera loopback8080.
- `vietocr-gateway.service`, `vietocr-camera@desk.service`: đã enable và active.
- `/usr/local/bin/cloudflared`: bản2026.10.7, đã kiểm SHA-256 và chạy `--version`. Named tunnel Pi đang chạy bằng systemd.

User `vietocr` là tài khoản hệ thống không đăng nhập, có group video/spi/gpio; HTTP gateway không chạy root. SSH/RDP/Tailscale giữ nguyên. GPIO/TFT/còi chưa bật vì cần xác minh dây thực tế.

## Cài/cập nhật bundle đã build

```sh
# Thư mục staging phải riêng tư trước khi SCP credential từ Windows.
install -d -m 700 /home/admin/private-config
# Chuẩn bị gateway.json và hai token riêng trong private-config; không đưa chúng vào Git.
sudo sh install.sh /home/admin/vietocr-v4 /home/admin/private-config
systemctl status vietocr-gateway.service vietocr-camera@desk.service
curl http://127.0.0.1:5082/health/live
```

`install.sh` giới hạn quyền staging700/token600 trước khi kiểm config, thay binary nguyên tử rồi restart. Thành công sẽ xoá đúng hai bản sao token trong staging; credential live ở `/etc/vietocr/` vẫn giữ0600. Tham số thứ3 tuỳ chọn `gateway-test.json` chỉ dùng phát triển. Mẫu service/config nằm cạnh installer; chỉ chọn UVC mode webcam công bố và giữ capture trên loopback.

Kiểm lại 10/11/2026: Pi dùng compute/results `https://ocr.quangnew.tech`, telemetry dùng `/api/internal/v2/status` trên cùng hostname. Không cần SSH reverse-forward 15080/15082. Khi laptop tắt, backend/connector Windows phải mở lại theo DevTodo.md mục 8.4; dịch vụ Pi active không chứng minh compute đang chạy.

`install-tunnel.sh` cài riêng connector Pi bằng user `cloudflared`, config0640 và
UUID credential0600; không nhận `cert.pem` quản lý tài khoản Cloudflare. Sau khi
connector active phải kiểm tra HTTPS từ máy khác trước khi chuyển compute origin.
Hướng dẫn tên miền/DNS/Authorize và hai connector nằm ở `DevTodo.md` tại root.

## Kiểm tra tải không đụng database thật

Bundle CI có `admission_probe` chỉ bind loopback, tạo signing key/danh tính fixture trong bộ nhớ và dùng fake Supabase/compute nội bộ:

```sh
./admission_probe 1000 3 > admission-probe.json
```

Nó chạy mã auth/relay thật nhưng **không phải 1000 Google login/Supabase/OCR thật**. RSS bao gồm cả fixture và bộ phát tải trong cùng process. Không expose probe hoặc raw µStreamer ra Internet. `camera_probe http://127.0.0.1:8080 10` đo broker camera riêng.


## Tự chạy sau reboot / Wi-Fi lên muộn

Ba service có `WantedBy=multi-user.target`, `Restart=on-failure`, `RestartSec=5`
và không chặn thử lại sau một vài lần lỗi. Gateway/tunnel đợi network-online.
Để enable lại runtime đã cài mà không chép credential hoặc restart dịch vụ
đang hoạt động: `sudo sh enable-autostart.sh`. Script cũng enable NetworkManager
wait-online và autoconnect cho profile Wi-Fi đang hoạt động.

Đã kiểm trên `rasp4gb` ngày 10/11/2026: cả ba `enabled`/`active`, Wi-Fi autoconnect
yes; không reboot hoặc ngắt Wi-Fi đang dùng. Hướng dẫn bật lại sau khi tắt laptop
và Pi: DevTodo.md mục 8.4–8.7. Compute/tunnel Windows vẫn cần mở lại bằng launcher.
