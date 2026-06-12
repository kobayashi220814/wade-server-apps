FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
WORKDIR /app
COPY requirements.txt .
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN pip install --no-cache-dir -r requirements.txt
# 預先下載 PP-OCRv5 mobile（det+cls+rec）模型烘進 image，執行時離線、冷啟動快
RUN python -c "from rapidocr import RapidOCR; from rapidocr.utils.typings import LangRec, LangDet, OCRVersion, ModelType; RapidOCR(params={'Det.ocr_version': OCRVersion.PPOCRV5, 'Det.model_type': ModelType.MOBILE, 'Det.lang_type': LangDet.CH, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE, 'Rec.lang_type': LangRec.CH})"
COPY . .
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
