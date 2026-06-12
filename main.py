import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from scraper import scrape_ppa_course, scrape_ppa_article

_scrape_semaphore = threading.Semaphore(3)
# OCR 是 CPU 密集（舊筆電），序列化避免互相拖垮
_ocr_semaphore = threading.Semaphore(1)

def _acquire_or_busy():
    if not _scrape_semaphore.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail=(
                "Server is busy — all scraping slots are occupied. "
                "Please retry after 15–30 seconds."
            ),
            headers={"Retry-After": "20"},
        )

app = FastAPI(
    title="PPA Scraper API",
    description="爬取 PressPlay Academy 課程頁（14 區塊）或文章頁（標題、內文、連結）",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


ALL_COURSE_FIELDS = [
    "title", "rating", "student_count", "overview",
    "what_you_learn", "target_audience", "price", "images",
    "curriculum", "instructor_names", "instructor_descriptions",
    "organizer_name", "organizer_description", "categories",
]


class ScrapeRequest(BaseModel):
    url: HttpUrl
    fields: list[str] | None = None


class OcrCourseRequest(BaseModel):
    url: HttpUrl


class OcrImagesRequest(BaseModel):
    urls: list[HttpUrl]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/scrape/course")
def scrape_course(req: ScrapeRequest):
    """
    爬取 PPA 課程頁（URL 必須含 `/about`）。
    fields 省略時回傳全部欄位；指定時只回傳指定欄位（速度更快）。
    可用欄位：title, rating, student_count, overview, what_you_learn,
    target_audience, price, images, curriculum, instructor_names,
    instructor_descriptions, organizer_name, organizer_description, categories
    """
    url = str(req.url)
    if "/about" not in url:
        raise HTTPException(
            status_code=400,
            detail="URL 不符合課程頁格式，應包含 /about（例如 .../project/xxx/about）",
        )
    fields = req.fields or ALL_COURSE_FIELDS
    invalid = [f for f in fields if f not in ALL_COURSE_FIELDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"無效的欄位：{invalid}。可用欄位：{ALL_COURSE_FIELDS}",
        )
    _acquire_or_busy()
    try:
        return scrape_ppa_course(url, fields)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _scrape_semaphore.release()


@app.post("/api/ocr/course")
def ocr_course(req: OcrCourseRequest):
    """
    給課程頁 URL（須含 `/about`），自動爬取介紹區圖片並做 OCR。
    回傳 {"images": [{"url": ..., "text": ...}]}，text 已簡轉繁（台灣用語）。
    """
    from ocr import ocr_image_urls

    url = str(req.url)
    if "/about" not in url:
        raise HTTPException(
            status_code=400,
            detail="URL 不符合課程頁格式，應包含 /about（例如 .../project/xxx/about）",
        )
    _acquire_or_busy()
    try:
        scraped = scrape_ppa_course(url, ["images"])
        image_urls = scraped.get("images", [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"爬取圖片失敗：{e}")
    finally:
        _scrape_semaphore.release()

    with _ocr_semaphore:
        try:
            results = ocr_image_urls(image_urls)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR 失敗：{e}")
    return {"count": len(results), "images": results}


@app.post("/api/ocr/images")
def ocr_images(req: OcrImagesRequest):
    """
    直接對一組圖片 URL 做 OCR（不經爬蟲）。
    回傳 {"images": [{"url": ..., "text": ...}]}，text 已簡轉繁（台灣用語）。
    """
    from ocr import ocr_image_urls

    urls = [str(u) for u in req.urls]
    with _ocr_semaphore:
        try:
            results = ocr_image_urls(urls)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR 失敗：{e}")
    return {"count": len(results), "images": results}


@app.post("/api/scrape/article")
def scrape_article(req: ScrapeRequest):
    """
    爬取 PPA 文章頁（URL 必須含 `/articles/`），回傳 title、content、links、publish_date。
    """
    url = str(req.url)
    if "/articles/" not in url:
        raise HTTPException(
            status_code=400,
            detail="URL 不符合文章頁格式，應包含 /articles/（例如 .../articles/xxx）",
        )
    _acquire_or_busy()
    try:
        return scrape_ppa_article(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _scrape_semaphore.release()
