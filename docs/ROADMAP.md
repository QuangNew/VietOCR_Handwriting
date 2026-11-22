# Hướng phát triển VietHandOCR

Ưu tiên hiện tại là đổi theme ổn định, phục hồi khi AI lỗi và kết nối BLE.
Các mục sau cần làm sau khi có bản chạy ổn định trên điện thoại mục tiêu.

| Ưu tiên | Hạng mục | Cách đánh giá |
| --- | --- | --- |
| 1 | Tập kiểm thử chữ Việt thực tế: nhiều nét chữ, dấu, giấy, ánh sáng | CER/WER, tỷ lệ dòng rỗng; tách người viết giữa train và test |
| 1 | Đo RAM đỉnh, thời gian nạp/đọc, frame chậm và lỗi native trên Android | Cùng ảnh, cùng thiết bị, nhiều lượt; lưu phiên bản model và runtime |
| 2 | Cắt vùng đọc, chỉnh phối cảnh, cảnh báo ảnh mờ/tối trước OCR | So CER/WER và số lần phải chụp lại trước/sau |
| 2 | Phát hiện vùng chữ và bố cục nhiều cột, tô vùng đang đọc | Thứ tự đọc đúng, không mất dấu; thời gian và RAM của cả pipeline |
| 2 | Độ tin cậy theo dòng và gợi ý sửa dấu/từ | Đánh dấu vùng cần kiểm tra; giữ văn bản gốc, cho người dùng chọn sửa |
| 3 | Lịch sử tìm kiếm, xuất PDF có lớp text, đọc văn bản bằng TTS Android | Khôi phục dữ liệu, chọn/xóa lịch sử, hoạt động offline |

## Giảm dung lượng và thời gian đọc sâu hơn

- Hiện tại: FP16 lưu trữ, FP32 tính toán; model mobile 74,3 MiB và desktop
  73,2 MiB. Bản FP32 gốc được giữ để đối chiếu. APK ARM64 giảm từ 182,3 xuống
  104,1 MiB. Chưa có số đo tốc độ/RAM trên máy thật ở thời điểm viết lộ trình.
- INT8: thử nghiệm hiện tại đổi văn bản mẫu nên chưa dùng. Cần dữ liệu hiệu
  chỉnh đại diện, so CER/WER toàn tập và thử QAT khi hậu lượng tử hóa chưa đạt.
- Model nhỏ: thử encoder MobileNet và decoder CTC hoặc transformer nhỏ qua
  distillation; phải đo riêng chất lượng dấu tiếng Việt, số và tên riêng.
- Decoder hiện tính lại prefix từng token. Nghiên cứu cache attention/KV để
  giảm tính lặp, kèm kiểm chứng đầu ra và giới hạn bộ nhớ.
- Build ONNX Runtime chỉ gồm các toán tử của model và phát hành ARM64 giúp
  giảm thư viện native; cần kiểm tra đầy đủ các hình dạng động và phiên bản
  runtime sau mỗi lần export.
- Desktop dùng chung ONNX có thể bỏ PyTorch khỏi gói chạy CPU. Giữ công cụ
  huấn luyện/export trong môi trường riêng để không kéo vào bản phân phối.

## IoT

Đã có chụp OV3660, xem trực tiếp trên TFT và truyền JPEG qua characteristic BLE
riêng; xem [hướng dẫn camera](../pbl4/docs/CAMERA.md). Cần kiểm chứng pinout bo
thật, tốc độ truyền/MTU và chất lượng ảnh trước khi tối ưu độ phân giải/ánh sáng.
App nhận ảnh tuần tự và lưu hàng đợi trên thiết bị. Có thể thêm chọn độ sáng, lịch ngủ và mute
được lưu; đổi độ sáng thật cần nối LED/backlight qua chân điều khiển phù hợp
vì hiện LED nối cố định 3V3. TMB12A05 chỉ phát beep; muốn đọc thành tiếng trên
ESP32 cần mạch phát âm thanh và loa. TTS trên điện thoại là bước có thể làm
trước khi thay phần cứng.
