from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from scraper import scrape_ppa_course, scrape_ppa_article

app = FastAPI(
    title="PPA Scraper API",
    description="爬取 PressPlay Academy 課程頁（14 區塊）或文章頁（標題、內文、連結）",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    url: HttpUrl


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/scrape")
def scrape(req: ScrapeRequest):
    """
    自動判斷 PPA 頁面類型並爬取：

    - URL 含 `/articles/` → 文章頁：回傳 title、content、links、publish_date
    - URL 含 `/about` → 課程頁：回傳 14 個區塊
    """
    url = str(req.url)
    try:
        if "/articles/" in url:
            return scrape_ppa_article(url)
        else:
            return scrape_ppa_course(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
