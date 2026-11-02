import os
from copy import deepcopy
import cv2
import numpy as np
from PIL import Image
import warnings

# =========================================================================
# FIX WARNINGS (Monkeypatch)
# Xử lý tận gốc các tham số gây ra warning bên trong thư viện `vietocr`
# mà không cần phải can thiệp sửa mã nguồn của package pip.
# =========================================================================

# Chỉ giữ tương thích Pillow cho VietOCR cũ; tránh sửa hàm toàn cục của PyTorch.
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = getattr(Image.Resampling, 'LANCZOS', getattr(Image, 'LANCZOS', 1))

# =========================================================================
# 1. MODEL CONFIGURATION
# Định nghĩa cấu hình trực tiếp (lấy từ config_vgg_transformer.yml) 
# để file này có thể hoạt động hoàn toàn độc lập.
# =========================================================================
MODEL_CONFIG = {
    'aug': {
        'image_aug': True,
        'masked_language_model': True
    },
    'backbone': 'vgg19_bn',
    'cnn': {
        'hidden': 256,
        'ks': [[2, 2], [2, 2], [2, 1], [2, 1], [1, 1]],
        'pretrained': True,
        'ss': [[2, 2], [2, 2], [2, 1], [2, 1], [1, 1]]
    },
    'dataloader': {
        'num_workers': 0
    },
    'dataset': {
        'data_root': '',
        'image_height': 32,
        'image_max_width': 1024,
        'image_min_width': 32,
        'name': 'data',
        'train_annotation': '/kaggle/working/clean_train_line.txt',
        'valid_annotation': '/kaggle/working/clean_val_line.txt'
    },
    'device': 'cpu',  # Mặc định sử dụng CPU
    'optimizer': {
        'max_lr': 0.0003,
        'pct_start': 0.1
    },
    'predictor': {
        'beamsearch': False
    },
    'pretrain': 'https://vocr.vn/data/vietocr/vgg_transformer.pth',
    'quiet': False,
    'seq_modeling': 'transformer',
    'trainer': {
        'batch_size': 32,
        'checkpoint': '/kaggle/working/checkpoints/best_val_checkpoint.pth',
        'export': '/kaggle/working/checkpoints/vgg_transformer_final.pth',
        'iters': 4000,
        'log': './train.log',
        'log_interval': 50,
        'lr': 0.0001,
        'metrics': None,
        'print': True,
        'print_every': 200,
        'save_dir': '/kaggle/working/checkpoints',
        'valid_every': 4000,
        'valid_interval': 500
    },
    'transformer': {
        'd_model': 256,
        'dim_feedforward': 2048,
        'max_seq_length': 1024,
        'nhead': 8,
        'num_decoder_layers': 6,
        'num_encoder_layers': 6,
        'pos_dropout': 0.1,
        'trans_dropout': 0.1
    },
    'vocab': 'aAàÀảẢãÃáÁạẠăĂằẰẳẲẵẴắẮặẶâÂầẦẩẨẫẪấẤậẬbBcCdDđĐeEèÈẻẺẽẼéÉẹẸêÊềỀểỂễỄếẾệỆfFgGhHiIìÌỉỈĩĨíÍịỊjJkKlLmMnNoOòÒỏỎõÕóÓọỌôÔồỒổỔỗỖốỐộỘơƠờỜởỞỡỠớỚợỢpPqQrRsStTuUùÙủỦũŨúÚụỤưƯừỪửỬữỮứỨựỰvVwWxXyYỳỲỷỶỹỸýÝỵỴzZ0123456789!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~ ',
    'weights': 'https://vocr.vn/data/vietocr/vgg_transformer.pth'
}

# =========================================================================
# 2. DIP PIPELINE (Digital Image Processing)
# =========================================================================
class VietOCR_DIP_Pipeline:
    def __init__(self):
        # CLAHE chỉ dùng cho ảnh bị mất nét (tương phản cực thấp)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def determine_skew(self, image):
        """Dùng thuật toán Projection Profile để tìm góc nghiêng"""
        # Angle estimation needs the page structure, not millions of pixels
        # rotated 60 times. Apply the chosen angle to the original image below.
        height, width = image.shape[:2]
        scale = min(1.0, 600 / width, 400 / height)
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        _, thresh = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        angles = np.arange(-15.0, 15.0, 0.5)
        scores = []
        for angle in angles:
            M = cv2.getRotationMatrix2D((thresh.shape[1]//2, thresh.shape[0]//2), angle, 1.0)
            rotated = cv2.warpAffine(thresh, M, (thresh.shape[1], thresh.shape[0]), flags=cv2.INTER_NEAREST)
            proj = np.sum(rotated, axis=1)
            score = np.sum((proj[1:] - proj[:-1]) ** 2)
            scores.append(score)
        best = max(scores)
        # Uniform/blank pages have tied scores; do not arbitrarily rotate -15°.
        return min((angle for angle, score in zip(angles, scores) if score == best), key=abs)

    def deskew(self, image):
        best_angle = self.determine_skew(image)
        if abs(best_angle) < 0.5:
            return image
            
        h_img, w_img = image.shape[:2]
        center = (w_img // 2, h_img // 2)
        M = cv2.getRotationMatrix2D(center, best_angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w_img, h_img), 
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
        return rotated

    def process_image(self, img_input):
        """
        Xử lý tiền kỳ bảo tồn. 
        Nhận đầu vào là đường dẫn ảnh (str) hoặc mảng Numpy (np.ndarray).
        """
        if isinstance(img_input, str):
            if not os.path.exists(img_input):
                warnings.warn(f"DIP Pipeline: File ảnh không tồn tại ở đường dẫn: {img_input}")
                return None
            img = cv2.imread(img_input, cv2.IMREAD_GRAYSCALE)
            if img is None:
                warnings.warn(f"DIP Pipeline: OpenCV không thể đọc được ảnh tại: {img_input}")
                return None
        elif isinstance(img_input, np.ndarray):
            if len(img_input.shape) == 3:
                img = cv2.cvtColor(img_input, cv2.COLOR_BGR2GRAY)
            else:
                img = img_input.copy()
        else:
            warnings.warn("DIP Pipeline: Định dạng ảnh đầu vào không hợp lệ. Hãy truyền Path (str) hoặc Numpy Array.")
            return None

        # 1. Deskew: Bắt buộc để VGG không bị trượt nét
        img = self.deskew(img)

        # 2. CLAHE có điều kiện: CHỈ cứu nét nếu ảnh thực sự quá mờ (Std < 30)
        if np.std(img) < 30:
            img = self.clahe.apply(img)

        return img

# =========================================================================
# 3. CORE API CLASS
# =========================================================================
class VietHandOCR:
    def __init__(self, weight_path="vgg_transformer_final.pth", device='cpu'):
        """
        Khởi tạo API nhận diện chữ viết tay (VietHandOCR).
        :param weight_path: Đường dẫn tuyệt đối hoặc tương đối tới file model (.pth)
        :param device: 'cpu' hoặc 'cuda:0' (nếu có GPU)
        """
        self.config = deepcopy(MODEL_CONFIG)
        self.load_error = None
        
        # Ghi đè các thông số quan trọng
        self.config['device'] = device
        self.config['weights'] = weight_path
        self.config['cnn']['pretrained'] = False
        
        # Khởi tạo mô hình vietocr
        try:
            from desktop.torch_predictor import TorchPredictor
            self.predictor = TorchPredictor(self.config)
        except Exception as e:
            self.load_error = e
            warnings.warn(f"VietHandOCR: Không thể khởi tạo mô hình Predictor. Chi tiết lỗi: {str(e)}")
            self.predictor = None
            
        # Khởi tạo Digital Image Processing pipeline
        self.dip = VietOCR_DIP_Pipeline()

    def predict(self, image_input):
        """
        Thực hiện nhận diện văn bản từ ảnh đầu vào.
        
        :param image_input: Đường dẫn ảnh (str) hoặc mảng Numpy (np.ndarray)
        :return: Chuỗi văn bản OCR (str). Trả về chuỗi rỗng "" nếu có lỗi.
        """
        if self.predictor is None:
            warnings.warn("VietHandOCR: Predictor chưa được khởi tạo thành công.")
            return ""
            
        # 1. Tiền xử lý ảnh (Deskew, CLAHE)
        processed_img_np = self.dip.process_image(image_input)
        
        if processed_img_np is None:
            # Lỗi đã được cảnh báo trong dip.process_image
            return ""
            
        # 2. Chuyển đổi sang định dạng PIL Image để feed vào VietOCR
        try:
            img_pil = Image.fromarray(processed_img_np)
        except Exception as e:
            warnings.warn(f"VietHandOCR: Lỗi chuyển đổi ảnh Numpy sang PIL. Chi tiết: {str(e)}")
            return ""
            
        # 3. Chạy quá trình inference
        try:
            text = self.predictor.predict(img_pil)
            return text
        except Exception as e:
            warnings.warn(f"VietHandOCR: Quá trình model nhận diện thất bại. Chi tiết: {str(e)}")
            return ""

# =========================================================================
# 4. TESTING MÔI TRƯỜNG TẠI CHỖ
# =========================================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="VietHandOCR Standalone API Test")
    parser.add_argument("--image", type=str, default="test.jpg", help="Đường dẫn tới ảnh thử nghiệm")
    parser.add_argument("--weights", type=str, default="vgg_transformer_final.pth", help="Đường dẫn model weights")
    parser.add_argument("--device", type=str, default="cpu", help="Thiết bị chạy: 'cpu' hoặc 'cuda:0'")
    args = parser.parse_args()

    print(f"[*] Đang khởi tạo mô hình VietHandOCR (Device: {args.device}) ...")
    ocr = VietHandOCR(weight_path=args.weights, device=args.device)
    
    print(f"[*] Đang đọc và nhận diện ảnh: {args.image} ...")
    result = ocr.predict(args.image)
    
    print(f"\n[+] Kết quả nhận diện:\n----------------------\n{result}\n----------------------")
