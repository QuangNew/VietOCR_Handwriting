# Native preprocessing của VietHandOCR

`viethandocr_application.py` lấy từ bộ bàn giao `viethandocr_enterprise_handoff` ngày 19/11/2026. Tác giả của pipeline giữ nguyên trong mã và giấy phép VietOCR đi kèm. `fixtures/` giữ trang mẫu và bản chép tham chiếu của nhóm.

Worker dùng cấu hình `auto_without_rectification` của handoff. Handoff phân biệt trang sạch với ảnh có nền phức tạp hoặc ánh sáng không đều. Nó tìm mực, tách dòng Native, rồi chuẩn hóa lề V2c. Chế độ **Một dòng** chuẩn bị một vùng chữ duy nhất. Dữ liệu đi thẳng tới model đang nạp sẵn qua API dùng chung của CPU/CUDA/DirectML.

Bản server bỏ bước tự cài package trong CLI mẫu. Phần xuất hình và đo RAM của CLI được tách khỏi đường xử lý request. Worker giới hạn ảnh làm việc ở 4 megapixel và cạnh 4096 px để giới hạn RAM khi tách dòng. Ảnh lớn hơn được thu theo tỷ lệ cho bước OCR. Ảnh lưu trên client và kích thước ảnh trả về vẫn theo đầu vào đã định hướng EXIF. Vùng V2c quá cao trả lỗi xử lý ảnh có thể khắc phục bằng xoay hoặc cắt dòng.

Model ML_s44 dùng [`model_config.json`](../../models/ML_s44/model_config.json). Trọng số hiện có trùng SHA‑256 với handoff. `tools/Check-ModelRelease.ps1` kiểm từ thư mục gốc của repo.

Kiểm pipeline thật từ thư mục gốc:

```powershell
services/compute/.venv/Scripts/python.exe -X utf8 services/compute/tools/check_native_worker.py --device cpu
services/compute/.venv/Scripts/python.exe -X utf8 services/compute/tools/check_native_worker.py --device cuda:0
```

Script giao tiếp với worker qua NDJSON như backend, kiểm hai dòng theo thứ tự, ảnh trắng, một dòng, ảnh lớn và khả năng dùng lại một model. Mẫu bàn giao ra `trơi` ở dòng đầu, thay vì `trời` trong tham chiếu. Đây là kiểm tích hợp trên mẫu nhỏ, số liệu CER/WER của nhóm nằm trong tài liệu bàn giao gốc.
