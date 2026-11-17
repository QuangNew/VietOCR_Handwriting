# AI release source

Thư mục này giữ mã và cấu hình model của nhóm AI, ảnh mẫu và license để đối chiếu
và đồng bộ sang [Server/models](../Server/models). Client desktop đã chuyển sang
[Tauri 2](../Desktop/README.md); mã Tk/BLE/ESP32/OV và launcher Python cũ đã gỡ.

Mở [Run-VietOCR.cmd](Run-VietOCR.cmd) hoặc [Desktop/Run-Desktop.cmd](../Desktop/Run-Desktop.cmd).
Client không cần Python, không chứa model, dùng webcam Raspberry và chỉ gửi ảnh
khi người dùng nhấn **Gửi**. `app.py` chỉ là lối mở tương thích cho EXE native.

Môi trường Python/CUDA phục vụ compute nằm tại `Server/.venv`, interpreter tại
`Server/.python`. Không xoá hai thư mục này khi dọn client. Trọng số, vocab,
kiến trúc và bước tiền xử lý của bản AI được giữ nguyên. `AI.py` dùng adapter
thuần model [model_api.py](model_api.py), không import ứng dụng desktop.

Kiểm tra bản AI offline bằng interpreter của server, từ thư mục này:

```powershell
../Server/.venv/Scripts/python.exe -X utf8 tools/validate_model.py --device cuda:0 --report ../.toolchain/refactor/ai-release-check.json
```

Đây là kiểm tra phát triển trên host compute, không phải OCR local trong app.
Triển khai thực tế và các hạng mục còn chờ được ghi ở
[REFACTOR_PROGRESS.md](../docs/REFACTOR_PROGRESS.md).
