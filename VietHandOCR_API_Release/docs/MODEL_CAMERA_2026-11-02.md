# Desktop + OV5640 — 02/11/2026

> Báo cáo lịch sử trước khi pull bộ nạp ML_s44 của nhóm AI. Các phép đối chiếu
> decoder dưới đây đã chạy theo cấu hình VietOCR cũ 32 px, chưa phải cấu hình
> ML_s44 64 px/V2c. Kết quả đó không xác nhận đúng tiền xử lý của model mới.
> Mặc định hiện tại và phép thử đã sửa xem [REVIEW_2026-11-02.md](REVIEW_2026-11-02.md).

## Model đã áp dụng

- Mặc định desktop và `VietHandOCR()` chuyển sang `ml_s44_fp16.pth` (76.492.147 bytes). Có thể chọn model khác bằng `--weights` hoặc Cài đặt model.
- SHA256: `644f2613046e4974c3aea5878e61d119b9100debe05cb55756b85b8241254cb2`.
- Đã nạp strict 302 tensor với VGG19-BN/Transformer 6 encoder + 6 decoder, d_model256, đầu ra233. Checkpoint FP16 được tính bằng FP32; không nén tiếp hoặc thay decoder/vocab để ép vừa model.
- Kiểm tra 5 ảnh mẫu trên CUDA RTX4050 và CPU: decoder tối ưu trả đúng cùng văn bản với decoder tham chiếu VietOCR ở cả 5 ảnh trên mỗi thiết bị. Đây là kiểm tra tương thích, **không phải độ chính xác 100%**: một số câu trong mẫu vẫn sai từ/dấu.
- Trọng số không chứa thứ tự vocab riêng để đối chiếu với quá trình huấn luyện; hình dạng tensor khớp và kết quả mẫu có nghĩa, nhưng muốn đánh giá CER/WER cần tập ảnh + nhãn chuẩn từ model mới.
- Thời gian nạp predictor sau import trên GPU khoảng 1,15 giây trong lượt đo riêng; trong GUI khoảng 1,60 giây. Khởi động tiến trình/import PyTorch và dò GPU mất thêm thời gian, không nằm trong con số này. Suy luận CUDA các ảnh sau warmup khoảng 0,15–0,58 giây; CPU khoảng 0,17–0,66 giây tùy chiều dài dòng.
- Bộ DirectML ONNX cũ khác hash nên không được dùng thay checkpoint mới. CUDA/CPU đã kiểm tra thật; chưa xuất ONNX DirectML cho model mới, chưa cập nhật Android.

Kết quả chi tiết: [CPU](../validation/ml-s44-cpu.json), [CUDA](../validation/ml-s44-cuda.json), [GUI + isolated worker](../validation/ml-s44-ui.log).

## Camera và preset trong desktop

Firmware `3.1.0-ocr` đã build, nạp và kiểm thử COM8. Đợi AF khóa ở độ phân giải chụp, bỏ frame cũ, đợi AEC/AGC hội tụ có giới hạn trước khi gửi JPEG 2592×1944/CRC32. Desktop dịch `CAMERA_FOCUS`/`CAMERA_EXPOSURE` sang thông báo có hướng xử lý và luôn giải phóng ảnh chờ, không tự bấm lại shutter.

Vào **Xem camera → Cấu hình camera → Tài liệu OCR → Áp dụng**. Preset preview640/QS18/max30, still5MP/QS6, màu/tương phản/sharpen trung tính, AF và phơi sáng tự động. Giữ nguyên hmirror/vflip từ thiết bị. Bo hiện được thử với hướng `hmirror=0, vflip=1` mà người dùng đã lưu trước lượt này; chữ trong ảnh giấy đúng chiều đọc. Có thể dùng hai ô Lật ngang/Lật dọc để chỉnh theo cách lắp camera, không lật thêm trong app.

Xem [nghiên cứu và quy trình camera](../../pbl4/docs/OCR_CAPTURE.md), dựa trên driver/AF của Espressif, camera webserver và hướng dẫn chất lượng ảnh OCR.

## Thử trang giấy do người dùng đặt

Chụp qua đường truyền desktop thật (`capture_fast` + HTTP + CRC), điều khiển được thay BLE bằng Serial để kiểm tra độc lập. Hai JPEG nguyên gốc có đủ 2592×1944:

- Cấu hình cũ: QS5, contrast1, sharpness2, denoise4, maxFPS10; JPEG692593bytes.
- Preset OCR: QS6, contrast0, sharpness0, denoise0, maxFPS30; JPEG439004bytes, vùng giấy ít bị quá sáng hơn. Không suy ra mọi ảnh sẽ giảm cùng tỷ lệ.
- Camera báo AF khóa khoảng1,3s, tạo JPEG native khoảng2s. LAN hiện tại cần thêm khoảng5–10s để tải ảnh; lượt đầu khởi tạo AF lạnh mất thêm khoảng5s. Preview thực hai lượt **10,29 và9,27FPS**, chưa đạt15–30FPS ở môi trường này; mở lạnh7,08s, mở lại khi còn ấm1,27s.
- Đọc bằng mắt được **“Chúc giáng sinh vui vẻ”** nhưng nét mềm, có bóng/giấy nghiêng. Model trên crop `(580,760,1380,1120)` nhận sai: `Cho quảng trưởng.` ở cấu hình cũ và `cho quảng biết` ở preset. [Kết quả thực](../validation/ml-s44-camera-paper.json).
- Thử riêng cân bằng nền/deskew cho ra một trường hợp gần đúng `Chức giảng sinh vui về` kèm dòng nhiễu, nhưng không ổn định trên ảnh còn lại. Vì vậy chưa đưa phép biến đổi thử nghiệm này vào mặc định hoặc tuyên bố đã sửa độ chính xác.

Ảnh local: `.toolchain/ocr-paper/original.jpg`, `.toolchain/ocr-paper/ocr.jpg` ở gốc workspace. Không gửi ảnh lên dịch vụ OCR ngoài. Chọn vùng chữ bằng trình xem Ảnh gốc, tránh hình vẽ/bàn; đặt camera song song giấy và ánh sáng đều để đánh giá model chính xác hơn.

## Build và kiểm tra

- 182 unittest desktop: PASS; gồm pipeline ảnh, queue, UI, worker crash/timeout, BLE, UDP, HTTP/CRC, preset OCR và model mặc định mới.
- GUI thật chạy 4 ảnh mẫu + trang 2 dòng: PASS về hoàn thành/xử lý hàng đợi; UI event loop tiếp tục1190vòng trong suy luận. Không coi các câu trả về là nhãn đúng.
- Toàn bộ host test IoT: PASS, gồm AF ACK/status timeout và exposure convergence mới; firmware PlatformIO build PASS, flash COM8 xác minh hash.
- Hai chu kỳ preview → chụp → preview: PASS JPEG/CRC; camera tự standby sau15s và mở lại: PASS. Lệnh Serial `POWER SLEEP` xác nhận sâu, không tự thức.
- Desktop `dist/VietOCR.exe` build thành công và kiểm tra môi trường `--check` PASS. File847364bytes là launcher dùng source/model/.venv của thư mục dự án, **không phải bản portable** để chép riêng sang máy khác.
- Firmware `pbl4/dist/VietOCR-OV5640.bin`,1505440bytes; SHA256 `ce2ed70236e8bce2cb390a1e468059a3c502d1c4d33c355f5c37881e872b4daa`.
- Desktop EXE SHA256 `8c676988febb57a2fbc6586bae40d74b7352e76eb6f02ca8d00710285b40c5fe`.

Không cài mới SDK/package/toolchain, không tải model thêm. Dùng Python/CUDA trong `VietHandOCR_API_Release/.venv`, PlatformIO có sẵn ở `C:/Users/QuangNew/.platformio`, MSYS2 compiler tại `C:/msys64/ucrt64`. Chỉ đọc tài liệu/mã nguồn web nhỏ. Không sửa/build Android.

Cuối lượt ESP32 ở **deep sleep**, COM8 đã đóng. Nhấn **EN/RESET** để dùng app; Wi-Fi/preset vẫn lưu NVS. Đèn nền nối3V3 có thể vẫn sáng, ngủ sâu không phải cắt nguồn vật lý.
