from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from scraper import scrape_ppa_course, scrape_ppa_article

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


class ScrapeRequest(BaseModel):
    url: HttpUrl


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/scrape/course")
def scrape_course(req: ScrapeRequest):
    """
    爬取 PPA 課程頁（URL 必須含 `/about`），回傳 14 個區塊。
    """
    url = str(req.url)
    if "/about" not in url:
        raise HTTPException(
            status_code=400,
            detail="URL 不符合課程頁格式，應包含 /about（例如 .../project/xxx/about）",
        )
    try:
        return scrape_ppa_course(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
        return scrape_ppa_article(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
