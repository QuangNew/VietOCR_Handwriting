# Triển khai Raspberry

Máy đã kiểm: Pi4B4GB `rasp4gb`, Raspberry Pi OS aarch64 / Debian13.7, µStreamer5.4, webcam `/dev/video0` native MJPEG1920×1080@30. Không cài Rust compiler lên Pi.

## Đường dẫn đã cài

- `/opt/vietocr/vietocr-gateway`: binary ARM64 từ CI.
- `/etc/vietocr/gateway.json`: cấu hình runtime, root:vietocr0640.
- `/etc/vietocr/ingress.token`, `/etc/vietocr/telemetry.token`: credential máy riêng,0600.
- `/etc/vietocr/camera-desk.env`: camera loopback8080.
- `vietocr-gateway.service`, `vietocr-camera@desk.service`: đã enable và active.
- `/usr/local/bin/cloudflared`: bản2026.10.7, đã kiểm SHA-256 và chạy `--version`. Connector chưa được cấu hình nếu chưa có Authorize/credential tunnel.

User `vietocr` là tài khoản hệ thống không đăng nhập, có group video/spi/gpio; HTTP gateway không chạy root. SSH/RDP/Tailscale giữ nguyên. GPIO/TFT/còi chưa bật vì cần xác minh dây thực tế.

## Cài/cập nhật bundle đã build

```sh
# Chuẩn bị gateway.json và hai token riêng trong private-config; không đưa chúng vào Git.
sudo sh install.sh /home/admin/vietocr-v4 /home/admin/private-config
systemctl status vietocr-gateway.service vietocr-camera@desk.service
curl http://127.0.0.1:5082/health/live
```

`install.sh` kiểm config bằng user service, thay binary nguyên tử rồi restart. Tham số thứ3 tuỳ chọn `gateway-test.json` chỉ dùng phát triển. Mẫu service/config nằm cạnh installer; chỉ chọn UVC mode webcam công bố và giữ capture trên loopback.

Bản đã triển khai thử hiện trỏ compute tới **SSH reverse-forward localhost:15080**, không phải đường truyền production. Khi tunnel compute HTTPS đã hoạt động, đổi `compute.origin` và `telemetry.url` sang `https://ocr.quangnew.tech` rồi restart gateway. Không để một kết nối SSH test trở thành phụ thuộc production ngầm định.

## Kiểm tra tải không đụng database thật

Bundle CI có `admission_probe` chỉ bind loopback, tạo signing key/danh tính fixture trong bộ nhớ và dùng fake Supabase/compute nội bộ:

```sh
./admission_probe 1000 3 > admission-probe.json
```

Nó chạy mã auth/relay thật nhưng **không phải 1000 Google login/Supabase/OCR thật**. RSS bao gồm cả fixture và bộ phát tải trong cùng process. Không expose probe hoặc raw µStreamer ra Internet. `camera_probe http://127.0.0.1:8080 10` đo broker camera riêng.
