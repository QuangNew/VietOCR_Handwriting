"""VietHandOCR bản gọn: đọc MỘT dòng chữ viết tay tiếng Việt, chỉ suy luận.

Chỉ cần torch, numpy, pillow, scipy. Không cần cài gói vietocr.

    from viethandocr_lite import LineRecognizer

    ocr = LineRecognizer()                    # nạp model một lần rồi dùng lại
    print(ocr.read("images/mot_dong.png"))    # đường dẫn hoặc PIL.Image

Kiến trúc VGG19-BN + Transformer viết lại theo VietOCR (Apache-2.0, xem
LICENSE_VietOCR.txt), giữ nguyên tên lớp để nạp đúng trọng số. V2c là bước cắt
lề giống lúc huấn luyện: tìm khung chữ bằng Otsu, kéo khung về rộng 2032 px, thêm
lề 8 px màu nền.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import unicodedata
import warnings

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage
import torch
from torch import nn

__all__ = ["LineRecognizer", "cer", "ink_bbox", "ink_bbox_v2", "ink_components", "ink_mask", "load_image",
           "normalize", "prepare_image", "sha256_file", "v2c_touches_border"]

DEFAULT_MODEL_DIR = Path(__file__).resolve().with_name("model")
PAD, SOS, EOS, MASK = 0, 1, 2, 3
MAX_DECODE_STEPS = 256
V2C_MARGIN_PX = 8
V2C_WIDTH_PX = 2048
VGG19_LAYERS = (64, 64, "P", 128, 128, "P", 256, 256, 256, 256, "P", 512, 512, 512, 512, "P", 512, 512, 512, 512, "P")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(text):
    return unicodedata.normalize("NFC", text).strip()


def cer(reference, prediction):
    """Tỉ lệ lỗi ký tự (Levenshtein / số ký tự nhãn) của một dòng; None nếu nhãn rỗng."""
    reference, prediction = normalize(reference), normalize(prediction)
    if not reference:
        return None
    previous = list(range(len(prediction) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(prediction, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1] / len(reference)


def load_image(path):
    """Đọc ảnh, xoay theo EXIF của điện thoại, trả về PIL.Image RGB."""
    with Image.open(path) as handle:
        return ImageOps.exif_transpose(handle).convert("RGB")


# ---------- V2c: cùng thuật toán với lúc huấn luyện ----------

def ink_mask(image):
    """Điểm ảnh tối hơn hoặc bằng ngưỡng Otsu là mực."""
    gray = np.asarray(image.convert("L"))
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    w0 = np.cumsum(hist)
    moment = np.cumsum(hist * np.arange(256))
    w1 = total - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (moment[-1] * w0 / total - moment) ** 2 / (w0 * w1)
    threshold = int(np.argmax(np.nan_to_num(between)))
    return gray <= threshold


def ink_bbox(image):
    """Khung lõi có nhiều mực (left, top, right, bottom), right/bottom không tính; None nếu không có mực."""
    mask = ink_mask(image)
    height, width = mask.shape
    columns = np.flatnonzero(mask.sum(0) >= max(2, int(0.01 * height)))
    rows = np.flatnonzero(mask.sum(1) >= max(2, int(0.005 * width)))
    if not len(columns) or not len(rows):
        return None
    return int(columns[0]), int(rows[0]), int(columns[-1] + 1), int(rows[-1] + 1)


def ink_components(image):
    """Nhãn các mảng mực liền nhau (nối 8 hướng) và diện tích; nền có diện tích 0."""
    labels, count = ndimage.label(ink_mask(image), structure=np.ones((3, 3), dtype=bool))
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    areas[0] = 0
    return labels, areas


def ink_bbox_v2(image):
    """Khung lõi, mở rộng để giữ trọn dấu và chân chữ dính gần (mảng từ 4 điểm ảnh)."""
    core = ink_bbox(image)
    if core is None:
        return None
    labels, areas = ink_components(image)
    left, top, right, bottom = core
    padding = int(np.ceil(0.25 * (bottom - top)))
    neighborhood = labels[max(0, top - padding):min(image.height, bottom + padding),
                          max(0, left - padding):min(image.width, right + padding)]
    kept = np.zeros(len(areas), dtype=bool)
    nearby = np.unique(neighborhood)
    kept[nearby[areas[nearby] >= 4]] = True
    ys, xs = np.nonzero(kept[labels])
    if not len(xs):
        return core
    return (min(left, int(xs.min())), min(top, int(ys.min())),
            max(right, int(xs.max()) + 1), max(bottom, int(ys.max()) + 1))


def _background_rgb(image, mask):
    rgb = np.asarray(image.convert("RGB"))
    pixels = rgb[~np.asarray(mask, dtype=bool)]
    if not len(pixels):
        pixels = rgb.reshape(-1, 3)
    return tuple(int(value) for value in np.median(pixels, axis=0))


def _normalize_margins(image, lr_px, tb_px, ref_width):
    box = ink_bbox_v2(image)
    info = {"bbox_found": box is not None, "bbox": box, "source_size": image.size,
            "lr_px": lr_px, "tb_px": tb_px, "ref_width": ref_width}
    if box is None:
        info["output_size"] = image.size
        return image.copy(), info
    background = _background_rgb(image, ink_mask(image))
    crop = image.convert("RGB").crop(box)
    width = ref_width - 2 * lr_px
    height = max(1, round(crop.height * width / crop.width))
    crop = crop.resize((width, height), Image.Resampling.LANCZOS)
    result = Image.new("RGB", (ref_width, height + 2 * tb_px), background)
    result.paste(crop, (lr_px, tb_px))
    info.update(background_rgb=background, content_size=crop.size, output_size=result.size)
    return result, info


def prepare_image(image, pre="v2c"):
    """Trả về (ảnh đưa vào model, thông tin V2c). pre: "v2c" hoặc "raw" (ảnh gốc, thông tin là None)."""
    if pre == "raw":
        return image.copy(), None
    if pre != "v2c":
        raise ValueError('pre phải là "v2c" hoặc "raw".')
    return _normalize_margins(image, V2C_MARGIN_PX, V2C_MARGIN_PX, V2C_WIDTH_PX)


def v2c_touches_border(audit):
    """True nếu khung V2c chạm mép ảnh: ảnh có bóng/viền tối, V2c có thể đã cắt không sát."""
    if not audit or not audit["bbox_found"]:
        return False
    left, top, right, bottom = audit["bbox"]
    width, height = audit["source_size"]
    return left == 0 or top == 0 or right == width or bottom == height


# ---------- Model: tên lớp giữ đúng như VietOCR để nạp strict ----------

class _Vgg(nn.Module):
    def __init__(self, ss, ks, hidden):
        super().__init__()
        layers, channels, pool = [], 3, 0
        for item in VGG19_LAYERS:
            if item == "P":
                layers.append(nn.AvgPool2d(kernel_size=ks[pool], stride=ss[pool], padding=0))
                pool += 1
            else:
                layers += [nn.Conv2d(channels, item, kernel_size=3, padding=1), nn.BatchNorm2d(item), nn.ReLU(inplace=True)]
                channels = item
        self.features = nn.Sequential(*layers)
        self.last_conv_1x1 = nn.Conv2d(512, hidden, 1)

    def forward(self, x):
        conv = self.last_conv_1x1(self.features(x))
        return conv.transpose(-1, -2).flatten(2).permute(-1, 0, 1)


class _Cnn(nn.Module):
    def __init__(self, ss, ks, hidden):
        super().__init__()
        self.model = _Vgg(ss, ks, hidden)

    def forward(self, x):
        return self.model(x)


class _PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len):
        super().__init__()
        self.register_buffer("pe", torch.zeros(max_len, 1, d_model))  # lấy từ file trọng số

    def forward(self, x):
        return x + self.pe[:x.size(0), :]


class _LanguageTransformer(nn.Module):
    def __init__(self, vocab_size, d_model, nhead, num_encoder_layers, num_decoder_layers, dim_feedforward,
                 max_seq_length, trans_dropout, **_):
        super().__init__()
        self.d_model = d_model
        self.embed_tgt = nn.Embedding(vocab_size, d_model)
        self.pos_enc = _PositionalEncoding(d_model, max_seq_length)
        self.transformer = nn.Transformer(d_model, nhead, num_encoder_layers, num_decoder_layers,
                                          dim_feedforward, trans_dropout)
        self.fc = nn.Linear(d_model, vocab_size)

    def forward_encoder(self, src):
        return self.transformer.encoder(self.pos_enc(src * math.sqrt(self.d_model)))

    def forward_decoder(self, tgt, memory):
        length = tgt.shape[0]
        mask = (torch.triu(torch.ones(length, length)) == 1).transpose(0, 1)
        mask = mask.float().masked_fill(mask == 0, float("-inf")).masked_fill(mask == 1, 0.0).to(tgt.device)
        tgt = self.pos_enc(self.embed_tgt(tgt) * math.sqrt(self.d_model))
        return self.fc(self.transformer.decoder(tgt, memory, tgt_mask=mask).transpose(0, 1))


class _VietOCR(nn.Module):
    def __init__(self, vocab_size, cnn, transformer):
        super().__init__()
        self.cnn = _Cnn(cnn["ss"], cnn["ks"], cnn["hidden"])
        self.transformer = _LanguageTransformer(vocab_size, **transformer)


class LineRecognizer:
    """Model đọc một dòng. Tạo một lần khi khởi động app rồi dùng lại; nạp mất vài giây.

    device: "cpu" hoặc "cuda". threads: số luồng CPU; None giữ mặc định của torch.
    """

    def __init__(self, model_dir=DEFAULT_MODEL_DIR, device="cpu", threads=None):
        model_dir = Path(model_dir)
        settings = json.loads((model_dir / "model_config.json").read_text(encoding="utf-8"))
        weights = model_dir / settings["weights_file"]
        if sha256_file(weights) != settings["weights_sha256"]:
            raise ValueError(f"File trọng số bị hỏng hoặc chép thiếu: {weights}")
        self._setup(settings, weights, device, threads)

    @classmethod
    def from_settings(cls, settings, weights, device="cpu", threads=None):
        """Nạp checkpoint khác cùng kiến trúc; settings gồm vocab, image_*, cnn, transformer."""
        self = cls.__new__(cls)
        self._setup(settings, weights, device, threads)
        return self

    def _setup(self, settings, weights, device, threads):
        if device != "cpu" and not torch.cuda.is_available():
            raise ValueError("Không thấy GPU NVIDIA. Dùng device='cpu'.")
        if threads is not None:
            torch.set_num_threads(threads)
        self.device = device
        self.height = int(settings["image_height"])
        self.min_width = int(settings["image_min_width"])
        self.max_width = int(settings["image_max_width"])
        self._chars = {i + 4: c for i, c in enumerate(settings["vocab"])}
        self._chars.update({PAD: "<pad>", SOS: "<sos>", EOS: "<eos>", MASK: "*"})
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="enable_nested_tensor")
            model = _VietOCR(len(settings["vocab"]) + 4, settings["cnn"], settings["transformer"])
        with open(weights, "rb") as handle:  # mở bằng Python để chạy được cả khi đường dẫn Windows có dấu
            state = torch.load(handle, map_location="cpu", weights_only=True)
        model.load_state_dict({k: v.float() if v.is_floating_point() else v for k, v in state.items()}, strict=True)
        self.model = model.to(device).eval()

    def read(self, image, pre="v2c"):
        """Đọc ảnh một dòng; image là đường dẫn hoặc PIL.Image. Trả về chuỗi đã chuẩn hóa NFC."""
        image = image.convert("RGB") if isinstance(image, Image.Image) else load_image(image)
        return self.predict(prepare_image(image, pre)[0])

    def input_image(self, image):
        """Ảnh đúng như model nhìn thấy: cao cố định, rộng làm tròn lên bội 10."""
        return image.convert("RGB").resize(self._input_size(*image.size), Image.Resampling.LANCZOS)

    def predict(self, image):
        """Đọc ảnh đã tiền xử lý xong, giải mã greedy tối đa 256 bước như lúc đánh giá."""
        array = np.asarray(self.input_image(image)).transpose(2, 0, 1) / 255
        tensor = torch.as_tensor(array).float().unsqueeze(0).to(self.device)
        with torch.inference_mode():
            memory = self.model.transformer.forward_encoder(self.model.cnn(tensor))
            tokens = [SOS]
            for _ in range(MAX_DECODE_STEPS + 1):
                target = torch.tensor(tokens, dtype=torch.long, device=self.device).unsqueeze(1)
                tokens.append(int(self.model.transformer.forward_decoder(target, memory)[0, -1].argmax()))
                if tokens[-1] == EOS:
                    tokens.pop()
                    break
        return normalize("".join(self._chars[token] for token in tokens[1:]))

    def _input_size(self, width, height):
        new_width = math.ceil(int(self.height * float(width) / float(height)) / 10) * 10
        return min(max(new_width, self.min_width), self.max_width), self.height
