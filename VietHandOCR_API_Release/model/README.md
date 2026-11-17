> **Ghi chú tích hợp (repo VietOCR_Handwriting).** Đây là README gốc của gói bàn giao `VietHandOCR_ML_s44_v1`; phần bên dưới giữ nguyên.
> Trong repo này các file của gói nằm như sau: `../viethandocr_lite.py` (code đọc ảnh), `model/` (thư mục này: `model_config.json` và trọng số),
> `../demo/` (notebook, ảnh mẫu, `requirements-notebook.txt`), `../LICENSE_VietOCR.txt`.
> Hướng dẫn cài đặt và chạy notebook bên dưới dành cho gói chạy riêng lẻ; với app desktop hãy làm theo [`../README.md`](../README.md).
> `requirements.txt` của gói đã được gộp vào `../requirements.txt` (thêm `scipy`).
>
> - File trọng số `.pth` **không nằm trong Git** (`*.pth` bị bỏ qua). Chép đúng file mà `model_config.json` chỉ định vào thư mục này;
>   `weights_sha256` trong cấu hình dùng để kiểm tra file không bị hỏng hay chép thiếu.
> - Trọng số lưu FP16 nhưng khi nạp được ép về FP32 để tính, cùng cách với `vgg_transformer_compact.pth` của dự án.
>   Muốn dùng bản FP32: thay cả file `.pth` lẫn `model_config.json` của bản đó, không cần sửa code.

---

# VietHandOCR: đọc chữ viết tay tiếng Việt theo dòng

Gói này nhận **ảnh một dòng chữ viết tay** và trả về văn bản tiếng Việt. Đã chạy thử bằng CPU trên Windows và Linux.

**Model chưa biết cắt dòng.** Ảnh cả trang phải được cắt thành từng dòng trước, nếu không kết quả sẽ sai.

## Trong gói có gì

| File | Dùng để |
| --- | --- |
| `viethandocr_lite.py` | Code đọc ảnh. App hoặc web chỉ cần file này và thư mục `model/` |
| `model/` | Trọng số 76 MB và cấu hình |
| `demo_nhan_dien.ipynb` | Notebook thử ảnh, vẽ từng bước xử lý |
| `images/` | 2 ảnh mẫu |
| `requirements.txt` | Thư viện cho app hoặc web |
| `requirements-notebook.txt` | Thư viện cho app hoặc web, thêm phần cho notebook |

## Cài đặt

Cần Python 64-bit. Đã chạy thử trên Windows 11 với Python 3.13 và 3.10, Linux với Python 3.12. Không cần GPU. Lần đầu pip sẽ tải khoảng 270 MB, sau khi cài chiếm khoảng 1 GB.

**Windows.** Mở Command Prompt hoặc PowerShell ngay trong thư mục này:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-notebook.txt
```

**Linux.** Dòng thứ hai để tránh bản CUDA nặng vài GB; máy có GPU NVIDIA thì bỏ dòng đó.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-notebook.txt
```

Nếu Windows báo không có lệnh `python`, thay bằng `py`.

Muốn dùng GPU trên Windows thì cài torch theo lệnh ở [pytorch.org](https://pytorch.org/get-started/locally/) trước, rồi mới chạy lệnh pip ở trên.

## Chạy notebook

1. Mở thư mục này bằng VS Code, mở `demo_nhan_dien.ipynb`.
2. Chọn kernel Python trong `.venv`.
3. Chạy Ô 1 một lần, rồi chạy Ô 2.
4. Muốn thử ảnh khác thì chép ảnh vào `images/`, sửa `IMAGE_PATHS` trong Ô 2, chạy lại Ô 2.

Mở notebook từ đúng thư mục này. Ô 1 tìm `viethandocr_lite.py` ở thư mục đang mở.

## Dùng trong app hoặc web

Chép `viethandocr_lite.py` và thư mục `model/` vào cùng một chỗ, cài `requirements.txt`, rồi:

```python
from viethandocr_lite import LineRecognizer

ocr = LineRecognizer(device="cpu", threads=2)   # chỉ nạp một lần, lúc khởi động
text = ocr.read("mot_dong.jpg")                 # nhận đường dẫn hoặc PIL.Image
```

Với ảnh gửi lên web dưới dạng bytes:

```python
import io
from viethandocr_lite import load_image

image = load_image(io.BytesIO(data))            # có xoay ảnh theo EXIF của điện thoại
text = ocr.read(image)
```

- Nạp model một lần rồi dùng lại. Nạp mất vài giây, khi đọc tiến trình chiếm khoảng 0,8 GB RAM.
- `ocr.read` đọc từng ảnh một. Trên CPU 2 luồng, một dòng 60–70 ký tự mất khoảng 2 giây, dòng ngắn khoảng 0,4 giây. Trong web hãy gọi nó ở worker riêng để không chặn server.
- `device="cuda"` để dùng GPU NVIDIA. Gói chưa được chạy thử trên GPU, nên hãy thử trước khi dựa vào.
- Kết quả là chuỗi Unicode NFC.

### Bước cắt lề V2c

`ocr.read` mặc định cắt lề bằng V2c, giống lúc huấn luyện. `ocr.read(image, pre="raw")` bỏ bước này.

V2c được làm cho ảnh quét nền sáng, đều. Với ảnh chụp có bóng hoặc viền tối, V2c có thể coi vùng tối là mực và cắt không sát. Kiểm tra được như sau:

```python
from viethandocr_lite import load_image, prepare_image, v2c_touches_border

image = load_image("mot_dong.jpg")
prepared, audit = prepare_image(image, "v2c")
text = ocr.predict(prepared)
if v2c_touches_border(audit):
    print("Khung cắt chạm mép ảnh, nên thử thêm pre='raw'")
```

Nhóm chưa đo xem cách nào tốt hơn trên ảnh chụp. Notebook có `COMPARE_BOTH = True` để xem cả hai cạnh nhau.

## Độ chính xác

| Đo trên | CER (lỗi ký tự) | WER (lỗi từ) | Số dòng |
| --- | ---: | ---: | ---: |
| UIT-HWDB validation, qua V2c | 2,13% | 6,15% | 678 |
| UIT-HWDB validation, ảnh gốc | 2,17% | 6,15% | 678 |

Đọc các số này cho đúng:

- **Đây chưa phải mức thật.** Tập validation đã được dùng để chọn model và nằm ở phía dễ. Model đời trước có validation 2,52% nhưng k-fold 3,84% và test 5,12%. Kỳ vọng model này cũng cao hơn con số trên. Nhóm đang làm k-fold để có số đáng tin hơn.
- **Chưa đo trên ảnh chụp điện thoại.** UIT-HWDB là ảnh dựng từ nét bút, không phải giấy chụp. Hai ảnh trong `images/` chỉ là ví dụ, không phải phép đo.
- Trên vài ảnh chụp thử, model hay thêm dấu chấm cuối dòng, và đôi khi đổi dấu tiếng Việt khi khung cắt thay đổi. Đây chỉ là quan sát trên vài ảnh.

## Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `OSError: [WinError 126]` khi `import torch` | Cài [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) |
| `OMP: Error #15` trên Windows, thường gặp với conda | Dùng venv như hướng dẫn trên |
| `Không thấy viethandocr_lite.py` trong notebook | Mở notebook từ đúng thư mục gói |
| `File trọng số bị hỏng hoặc chép thiếu` | Giải nén lại ZIP |
| `Không thấy GPU NVIDIA` | Đổi sang `device="cpu"` hoặc cài torch bản CUDA |
| `.heic` không mở được | Đổi ảnh sang JPG hoặc PNG |

## Nguồn gốc và giấy phép

- Model `ML_s44`: VietOCR (VGG19-BN + Transformer) ảnh cao 64 px, fine-tune từ checkpoint công khai của VietOCR trên UIT-HWDB line, 8.000 bước, thêm lề ngẫu nhiên khi huấn luyện, seed 44. Chọn trong 3 seed theo CER validation.
- Trọng số lưu dạng float16 để giảm từ 152 MB xuống 76 MB. Đã so với bản float32 trên toàn bộ 678 dòng validation: 676/678 dòng đọc giống hệt trên ảnh V2c, 676/678 trên ảnh gốc; số lỗi ký tự 971 → 971 và 990 → 989.
- `viethandocr_lite.py` viết lại phần suy luận theo [VietOCR](https://github.com/pbcquoc/vietocr), giấy phép Apache-2.0, xem `LICENSE_VietOCR.txt`. Phần thay đổi: bỏ phần huấn luyện và phụ thuộc không cần cho suy luận, thêm V2c.
- Model học từ dữ liệu UIT-HWDB. Nhóm chưa kiểm tra điều khoản của bộ dữ liệu này cho việc phát hành công khai hoặc thương mại, nên hãy kiểm tra trước khi làm việc đó.
