# VietHandOCR API Release

Đây là gói API nhận diện chữ viết tay độc lập (Standalone API), có thể dễ dàng tích hợp vào bất kỳ ứng dụng Python nào.

## 1. Thành phần
- `AI.py`: Code chính chứa toàn bộ tiền xử lý ảnh (DIP) và bọc gọi mô hình OCR.
- `vgg_transformer_final.pth`: Trọng số (weights) của mô hình.
- `requirements.txt`: Danh sách các thư viện cần cài đặt.
- `test.jpg`, `test2.jpg`: Ảnh để chạy thử nghiệm.

## 2. Hướng dẫn cài đặt
Cài đặt các thư viện cần thiết thông qua pip:
```bash
pip install -r requirements.txt
```
*(Khuyến nghị sử dụng Python 3.8+)*

## 3. Cách test nhanh (Command Line)
Chạy trực tiếp file `AI.py` bằng Terminal/Command Prompt:
```bash
python AI.py --image test.jpg
python AI.py --image test2.jpg
```

## 4. Cách tích hợp vào Code ứng dụng
Bạn có thể gọi Class `VietHandOCR` từ `AI.py` rất đơn giản như sau:

```python
import cv2
from AI import VietHandOCR

# Khởi tạo mô hình một lần duy nhất lúc khởi động app
ocr = VietHandOCR(weight_path="vgg_transformer_final.pth", device="cpu")

# 1. Truyền đường dẫn file
text1 = ocr.predict("test.jpg")
print("Kết quả 1:", text1)

# 2. Hoặc truyền trực tiếp ảnh OpenCV (numpy array) từ camera/server trả về
img = cv2.imread("test2.jpg")
text2 = ocr.predict(img)
print("Kết quả 2:", text2)
```
