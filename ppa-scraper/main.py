from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from scraper import scrape_ppa_course

app = FastAPI(
    title="PPA Course Scraper API",
    description="爬取 PressPlay Academy 課程頁面的 14 個核心區塊",
    version="1.0.0",
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
    爬取 PressPlay Academy 課程頁面。

    輸入 `url`（課程 about 頁面），回傳 14 個區塊：
    課程名稱、評價、學習人數、課程總覽、你可以學到、誰適合學習、
    價錢、介紹圖片、目錄、講師名稱、講師介紹、開課單位、相關分類。
    """
    try:
        return scrape_ppa_course(str(req.url))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
