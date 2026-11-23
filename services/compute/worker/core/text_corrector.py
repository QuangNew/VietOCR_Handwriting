"""Hau xu ly sua loi van ban OCR tieng Viet bang BARTpho FP16 + Edit Guard v3 + Ngu canh nhieu dong.

Chi duoc nap (lazy-load) khi nguoi dung tich chon tuy chon sua loi AI (`correct=True`).
Neu `correct=False`, worker chi chay ML_s44 va khong ton them RAM/VRAM.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import unicodedata

import torch

try:
    from rapidfuzz.distance.Levenshtein import distance as char_distance
except ImportError:
    def char_distance(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i]
            for j, cb in enumerate(b, 1):
                curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = curr
        return prev[-1]


PUNCT = '.,;:!?"\'()[]{}<>-–—…“”‘’/\\|*&%$#@^_`~+='
HYPHEN_TOKENS = {"-", "–", "—"}

DEFAULT_GUARD_CONFIG = {
    "max_word_dist": 3,
    "max_line_cer": 0.12,
    "preserve_case": False,
    "allow_word_ins_del": False,
    "allow_space_split": True,
    "protect_hyphenated": True,
    "protect_capitalized": False,
    "only_diacritic_or_close": False,
}


def norm_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text)).strip()


def strip_diacritics(text: str) -> str:
    t = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))


def split_punct(token: str) -> tuple[str, str, str]:
    s, e = 0, len(token)
    while s < e and token[s] in PUNCT:
        s += 1
    while e > s and token[e - 1] in PUNCT:
        e -= 1
    return token[:s], token[s:e], token[e:]


def match_case(src_core: str, pred_core: str) -> str:
    if not src_core or not pred_core:
        return pred_core
    if src_core.isupper() and len(src_core) > 1:
        return pred_core.upper()
    if src_core.islower():
        return pred_core.lower()
    if src_core[0].isupper() and src_core[1:].islower():
        return pred_core[0].upper() + pred_core[1:].lower()
    return pred_core


def sanitize_case(src_core: str, pred_core: str, preserve_case: bool) -> str:
    if not src_core or not pred_core:
        return pred_core
    if preserve_case:
        return match_case(src_core, pred_core)
    src_has_mid_upper = any(c.isupper() for c in src_core[1:])
    if not src_has_mid_upper and any(c.isupper() for c in pred_core[1:]):
        return pred_core[0] + pred_core[1:].lower()
    return pred_core


def hyphen_protected_indices(tokens: list[str]) -> set[int]:
    protected: set[int] = set()
    n = len(tokens)
    for k, tok in enumerate(tokens):
        _, core, _ = split_punct(tok)
        if "-" in core and all(p.isalpha() for p in core.split("-") if p):
            protected.add(k)
        if tok in HYPHEN_TOKENS and 0 < k < n - 1:
            _, left_c, _ = split_punct(tokens[k - 1])
            _, right_c, _ = split_punct(tokens[k + 1])
            if (
                left_c
                and right_c
                and left_c.isalpha()
                and right_c.isalpha()
                and len(left_c) <= 7
                and len(right_c) <= 7
            ):
                protected.add(k - 1)
                protected.add(k + 1)
    return protected


def apply_edit_guard(
    raw: str,
    pred: str,
    *,
    max_word_dist: int = 3,
    max_line_cer: float = 0.12,
    preserve_case: bool = False,
    allow_word_ins_del: bool = False,
    allow_space_split: bool = True,
    protect_hyphenated: bool = True,
    protect_capitalized: bool = False,
    only_diacritic_or_close: bool = False,
) -> str:
    """Khoa an toan v3: bao ve dau cau, so lieu, tu phien am gach noi, ho tro tach tu dinh khoang trang."""
    raw = norm_nfc(raw)
    pred = norm_nfc(pred)
    if not raw or not pred or raw == pred:
        return raw

    if char_distance(raw, pred) / max(len(raw), 1) > max(0.45, max_line_cer * 2.5):
        return raw

    raw_toks = raw.split()
    pred_toks = pred.split()
    hyph_prot = hyphen_protected_indices(raw_toks) if protect_hyphenated else set()
    sm = SequenceMatcher(None, [t.lower() for t in raw_toks], [t.lower() for t in pred_toks], autojunk=False)

    out_toks: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out_toks.extend(raw_toks[i1:i2])
        elif tag == "replace":
            r_span = raw_toks[i1:i2]
            p_span = pred_toks[j1:j2]
            if len(r_span) == len(p_span):
                for offset, (r_tok, p_tok) in enumerate(zip(r_span, p_span)):
                    r_idx = i1 + offset
                    if r_idx in hyph_prot:
                        out_toks.append(r_tok)
                        continue
                    r_pre, r_core, r_suf = split_punct(r_tok)
                    _, p_core, _ = split_punct(p_tok)
                    if not r_core or not p_core:
                        out_toks.append(r_tok)
                        continue
                    if any(c.isdigit() for c in r_core) or any(c.isdigit() for c in p_core):
                        out_toks.append(r_tok)
                        continue
                    if protect_capitalized and r_core[0].isupper():
                        out_toks.append(r_tok)
                        continue
                    cand = sanitize_case(r_core, p_core, preserve_case)
                    d = char_distance(r_core.lower(), cand.lower())
                    if d == 0:
                        out_toks.append(r_pre + cand + r_suf)
                        continue
                    if d <= max_word_dist:
                        if only_diacritic_or_close:
                            same_base = strip_diacritics(r_core.lower()) == strip_diacritics(cand.lower())
                            if not (same_base or d == 1):
                                out_toks.append(r_tok)
                                continue
                        out_toks.append(r_pre + cand + r_suf)
                    else:
                        out_toks.append(r_tok)
            elif allow_space_split and len(p_span) == len(r_span) + 1:
                split_k = None
                for k in range(len(r_span)):
                    if (i1 + k) in hyph_prot:
                        continue
                    _, rc, _ = split_punct(r_span[k])
                    _, p0c, _ = split_punct(p_span[k])
                    _, p1c, _ = split_punct(p_span[k + 1])
                    if (
                        len(rc) >= 5
                        and rc.isalpha()
                        and p0c.isalpha()
                        and p1c.isalpha()
                        and char_distance(rc.lower(), (p0c + p1c).lower()) <= 2
                    ):
                        split_k = k
                        break
                if split_k is not None:
                    for k, r_tok in enumerate(r_span):
                        r_idx = i1 + k
                        if k == split_k:
                            r_pre, r_core, r_suf = split_punct(r_tok)
                            _, p0c, _ = split_punct(p_span[k])
                            _, p1c, _ = split_punct(p_span[k + 1])
                            out_toks.append(r_pre + sanitize_case(r_core, p0c, preserve_case))
                            out_toks.append(sanitize_case(r_core.lower(), p1c, False) + r_suf)
                        else:
                            p_tok = p_span[k if k < split_k else k + 1]
                            if r_idx in hyph_prot:
                                out_toks.append(r_tok)
                                continue
                            r_pre, r_core, r_suf = split_punct(r_tok)
                            _, p_core, _ = split_punct(p_tok)
                            if not r_core or not p_core or any(c.isdigit() for c in r_core) or any(c.isdigit() for c in p_core):
                                out_toks.append(r_tok)
                                continue
                            cand = sanitize_case(r_core, p_core, preserve_case)
                            d = char_distance(r_core.lower(), cand.lower())
                            if d <= max_word_dist:
                                out_toks.append(r_pre + cand + r_suf)
                            else:
                                out_toks.append(r_tok)
                else:
                    out_toks.extend(r_span)
            else:
                r_str = " ".join(r_span)
                p_str = " ".join(p_span)
                if (
                    allow_word_ins_del
                    and not any(k in hyph_prot for k in range(i1, i2))
                    and not any(c.isdigit() for c in r_str)
                    and char_distance(r_str.lower(), p_str.lower()) <= max_word_dist
                ):
                    out_toks.extend(p_span)
                else:
                    out_toks.extend(r_span)
        elif tag == "delete":
            r_span = raw_toks[i1:i2]
            if allow_word_ins_del and len(r_span) == 1 and len(r_span[0]) <= 2 and r_span[0].isalpha():
                continue
            out_toks.extend(r_span)
        elif tag == "insert":
            p_span = pred_toks[j1:j2]
            if allow_word_ins_del and len(p_span) == 1 and len(p_span[0]) <= 4 and p_span[0].isalpha():
                out_toks.extend(p_span)

    result = norm_nfc(" ".join(out_toks))
    if char_distance(raw, result) / max(len(raw), 1) > max_line_cer:
        return raw
    return result


def align_chunk_to_lines(raw_lines: list[str], pred_chunk: str, guard_cfg: dict) -> list[str]:
    if len(raw_lines) == 1:
        return [apply_edit_guard(raw_lines[0], pred_chunk, **guard_cfg)]

    line_toks = [norm_nfc(line).split() for line in raw_lines]
    raw_all: list[str] = []
    spans: list[tuple[int, int]] = []
    for toks in line_toks:
        start = len(raw_all)
        raw_all.extend(toks)
        spans.append((start, len(raw_all)))

    pred_all = norm_nfc(pred_chunk).split()
    if not raw_all or not pred_all:
        return [norm_nfc(line) for line in raw_lines]

    sm = SequenceMatcher(None, [t.lower() for t in raw_all], [t.lower() for t in pred_all], autojunk=False)
    mapped_per_raw: list[list[str]] = [[] for _ in range(len(raw_all))]
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for off in range(i2 - i1):
                mapped_per_raw[i1 + off].append(pred_all[j1 + off])
        elif tag == "replace":
            r_len = i2 - i1
            p_len = j2 - j1
            if r_len == p_len:
                for off in range(r_len):
                    mapped_per_raw[i1 + off].append(pred_all[j1 + off])
            else:
                step, rem = divmod(p_len, r_len)
                cur = j1
                for off in range(r_len):
                    take = step + (1 if off < rem else 0)
                    mapped_per_raw[i1 + off].extend(pred_all[cur : cur + take])
                    cur += take
        elif tag == "delete":
            for idx in range(i1, i2):
                mapped_per_raw[idx].append(raw_all[idx])

    results: list[str] = []
    for raw_line, (s, e) in zip(raw_lines, spans):
        if s == e:
            results.append("")
            continue
        pred_line_toks: list[str] = []
        for idx in range(s, e):
            pred_line_toks.extend(mapped_per_raw[idx])
        results.append(apply_edit_guard(raw_line, " ".join(pred_line_toks), **guard_cfg))
    return results


def _ends_sentence(text: str) -> bool:
    t = text.rstrip(' "\'”’)]}')
    return bool(t) and t[-1] in ".!?"


def group_lines_into_chunks(lines: list[str], max_words: int = 45, max_lines: int = 3) -> list[list[int]]:
    chunks: list[list[int]] = []
    cur: list[int] = []
    cur_words = 0
    prev_text = ""
    for idx, line in enumerate(lines):
        normed = norm_nfc(line)
        w = len(normed.split())
        if w == 0:
            if cur:
                chunks.append(cur)
                cur, cur_words, prev_text = [], 0, ""
            chunks.append([idx])
            continue
        should_merge = bool(cur) and (not _ends_sentence(prev_text) or w <= 5)
        if not should_merge or cur_words + w > max_words or len(cur) >= max_lines:
            if cur:
                chunks.append(cur)
            cur, cur_words = [idx], w
        else:
            cur.append(idx)
            cur_words += w
        prev_text = normed
    if cur:
        chunks.append(cur)
    return chunks


class BartphoCorrector:
    """Bo sua loi van ban OCR bang BARTpho (FP16 tren CUDA, FP32 tren CPU)."""

    def __init__(self, model_dir: str | Path, device: str = "cpu", num_beams: int = 4) -> None:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()

        self.model_dir = Path(model_dir)
        if not self.model_dir.exists():
            raise FileNotFoundError(f"Khong tim thay thu muc model BARTpho: {self.model_dir}")

        if device.startswith("cuda") and torch.cuda.is_available():
            self.device = torch.device(device)
            self.dtype = torch.float16
        else:
            self.device = torch.device("cpu")
            self.dtype = torch.float32

        self.num_beams = num_beams
        guard_path = self.model_dir / "edit_guard_config.json"
        if guard_path.exists():
            loaded = json.loads(guard_path.read_text(encoding="utf-8"))
            self.guard_cfg = {**DEFAULT_GUARD_CONFIG, **loaded}
        else:
            self.guard_cfg = dict(DEFAULT_GUARD_CONFIG)

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), local_files_only=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            str(self.model_dir),
            dtype=self.dtype,
            local_files_only=True,
        ).to(self.device)
        self.model.eval()

    def parameter_mib(self) -> float:
        total = sum(p.numel() * p.element_size() for p in self.model.parameters())
        total += sum(b.numel() * b.element_size() for b in self.model.buffers())
        return total / 1048576.0

    @torch.inference_mode()
    def _generate_batch(self, texts: list[str], batch_size: int = 16, max_length: int = 256) -> list[str]:
        raw_preds: list[str] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            enc = self.tokenizer(
                chunk,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_length,
            ).to(self.device)
            max_new = min(max_length, int(enc["input_ids"].size(1) * 1.35) + 16)
            out = self.model.generate(
                **enc,
                max_new_tokens=max_new,
                num_beams=self.num_beams,
                early_stopping=True,
            )
            decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)
            raw_preds.extend(norm_nfc(d) for d in decoded)
        return raw_preds

    @torch.inference_mode()
    def correct_lines_with_meta(
        self,
        lines: list[str],
        batch_size: int = 16,
        use_context: bool = True,
    ) -> tuple[list[str], list[list[int]]]:
        """Sua loi danh sach dong va tra them nhom ngu canh (chunks) phuc vu truc quan hoa pipeline."""
        if not lines:
            return [], []
        normed = [norm_nfc(line) for line in lines]

        # Neu chi co 1 dong hoac tat ngu canh -> chay tung dong truc tiep
        if not use_context or len(normed) <= 1:
            raw_preds = self._generate_batch(normed, batch_size=batch_size, max_length=192)
            out = [
                apply_edit_guard(raw, pred, **self.guard_cfg) if raw else ""
                for raw, pred in zip(normed, raw_preds)
            ]
            return out, [[i] for i in range(len(normed))]

        # Gop thong minh chi cac dong noi tiep cung cau (khong ket thuc .!?) hoac dong ngan <=5 tu
        chunks = group_lines_into_chunks(normed, max_words=45, max_lines=3)
        chunk_texts = [" ".join(normed[i] for i in idxs if normed[i]) for idxs in chunks]
        non_empty_pos = [k for k, t in enumerate(chunk_texts) if t]
        chunk_preds = [""] * len(chunks)
        if non_empty_pos:
            preds = self._generate_batch([chunk_texts[k] for k in non_empty_pos], batch_size=batch_size, max_length=256)
            for k, p in zip(non_empty_pos, preds):
                chunk_preds[k] = p

        out_lines = list(normed)
        fallback_indices: list[int] = []
        for idxs, chunk_raw, chunk_pred in zip(chunks, chunk_texts, chunk_preds):
            if not chunk_raw:
                continue
            # Neu khoi bi thay doi bat thuong (>35% ky tu), fallback ve tung dong cho an toan
            if char_distance(chunk_raw, chunk_pred) / max(len(chunk_raw), 1) > 0.35:
                fallback_indices.extend(idxs)
                continue
            sub_raw = [normed[i] for i in idxs]
            sub_fixed = align_chunk_to_lines(sub_raw, chunk_pred, self.guard_cfg)
            for i, fixed in zip(idxs, sub_fixed):
                out_lines[i] = fixed

        if fallback_indices:
            fb_raws = [normed[i] for i in fallback_indices]
            fb_preds = self._generate_batch(fb_raws, batch_size=batch_size, max_length=192)
            for i, r, p in zip(fallback_indices, fb_raws, fb_preds):
                out_lines[i] = apply_edit_guard(r, p, **self.guard_cfg) if r else ""

        return out_lines, chunks

    @torch.inference_mode()
    def correct_lines(
        self,
        lines: list[str],
        batch_size: int = 16,
        use_context: bool = True,
    ) -> list[str]:
        """Sua loi danh sach dong cua 1 trang (tu dong gop khoi ngu canh 2-5 dong khi trang co nhieu dong)."""
        return self.correct_lines_with_meta(lines, batch_size=batch_size, use_context=use_context)[0]
