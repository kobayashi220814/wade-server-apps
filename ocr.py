"""
圖片 OCR 模組：PP-OCRv5 mobile 偵測 + 辨識，再用 OpenCC 簡轉繁（台灣用語）。

- 模型在 Docker build 階段預先下載並烘進 image（見 Dockerfile），執行時離線可用。
- 對 PPA 課程介紹圖（繁中行銷文案）準確度約 97%，舊筆電 CPU 上速度可接受。
"""
import io
import urllib.request

import cv2
import numpy as np
import opencc
from rapidocr import RapidOCR
from rapidocr.utils.typings import LangRec, LangDet, OCRVersion, ModelType

_engine = None
_cc = None


def _get_engine():
    """延遲初始化，避免 import 時就載入模型。"""
    global _engine, _cc
    if _engine is None:
        _engine = RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Det.lang_type": LangDet.CH,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.CH,
        })
        _cc = opencc.OpenCC("s2twp")
    return _engine, _cc


def _download_image(url: str, timeout: int = 30) -> "np.ndarray":
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("無法解碼圖片")
    return img


def ocr_image_url(url: str) -> str:
    """對單一圖片 URL 做 OCR，回傳簡轉繁後的純文字（各段落以換行分隔）。"""
    engine, cc = _get_engine()
    img = _download_image(url)
    res = engine(img)
    if not res.txts:
        return ""
    return "\n".join(cc.convert(t) for t in res.txts)


def ocr_image_urls(urls: list) -> list:
    """
    對多個圖片 URL 做 OCR。
    回傳 [{"url": ..., "text": ...}]，單張失敗時 text 為 None、附 error 欄位。
    """
    out = []
    for u in urls:
        try:
            out.append({"url": u, "text": ocr_image_url(u)})
        except Exception as e:
            out.append({"url": u, "text": None, "error": str(e)})
    return out
