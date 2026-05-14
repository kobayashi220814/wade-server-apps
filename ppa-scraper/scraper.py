from playwright.sync_api import sync_playwright
import re


def scrape_ppa_course(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # 等 h1 出現代表頁面主要內容已渲染
        page.wait_for_selector("h1", timeout=30000)

        result = {}

        # 1. 課程名稱
        el = page.query_selector("h1")
        result["title"] = el.inner_text().strip() if el else None

        body = page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]

        # 2. 評價（星數）
        m = re.search(r"(\d+\.\d+)\s*評價", body)
        result["rating"] = m.group(1) if m else None

        # 3. 學習人數
        m = re.search(r"([\d,]+)\s*人學習", body)
        result["student_count"] = m.group(1) if m else None

        # 4. 課程總覽（取最長的描述段落）
        try:
            idx = next(i for i, l in enumerate(lines) if l == "課程總覽")
            candidates = lines[idx + 1 : idx + 10]
            result["overview"] = max(candidates, key=len)
        except StopIteration:
            result["overview"] = None

        # 5. 你可以學到（只取 ★ 開頭的標題行）
        try:
            idx = next(i for i, l in enumerate(lines) if "你可以學到" in l)
            items = []
            for l in lines[idx + 1 :]:
                if "誰適合學習" in l:
                    break
                if l.startswith("★"):
                    items.append(l.replace("\xa0", " ").strip())
            result["what_you_learn"] = items
        except StopIteration:
            result["what_you_learn"] = []

        # 6. 誰適合學習（只取標題行，略過說明文字）
        try:
            idx = next(i for i, l in enumerate(lines) if "誰適合學習" in l)
            audiences = []
            for l in lines[idx + 1 :]:
                if re.match(r"\d+\.\d+\s*評價|顯示所有評價", l):
                    break
                # 短行視為受眾標題（說明文字通常很長）
                if len(l) <= 15:
                    audiences.append(l)
            result["target_audience"] = audiences
        except StopIteration:
            result["target_audience"] = []

        # 7. 價錢
        el = page.query_selector(
            "#about-section-side > div > div.purchase-info > "
            "div.purchase-info-price-container > div > span"
        )
        result["price"] = el.inner_text().strip() if el else None

        # 8. 介紹裡的圖片網址（展開「更多介紹」，只取課程內容圖片）
        for btn in page.query_selector_all(".pp-button-secondary"):
            if "更多介紹" in btn.inner_text():
                btn.click()
                page.wait_for_timeout(1500)
                break

        imgs = page.query_selector_all("img")
        img_srcs = []
        seen = set()
        for img in imgs:
            src = img.get_attribute("src") or ""
            # 只保留來自 pressplay CDN 的圖片，排除 /public/ UI 資源
            if (
                src
                and src not in seen
                and "static.pressplay.cc" in src
                and re.search(r"\.(jpg|jpeg|png|webp)", src, re.I)
            ):
                img_srcs.append(src)
                seen.add(src)
        result["images"] = img_srcs

        # 9. 目錄與試看（點 tab → 展開全部章節）
        tab = page.query_selector('[data-tab-id="public_articles"]')
        if tab:
            tab.click()
            page.wait_for_timeout(2000)

        for el in page.query_selector_all("*"):
            try:
                t = el.inner_text().strip()
                if "顯示全部章節" in t and len(t) < 30:
                    el.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

        body2 = page.inner_text("body")
        lines2 = [l.strip() for l in body2.split("\n") if l.strip()]

        # 抓帶子編號的課程目錄（格式：Lesson.X title (N) 和 X-Y 子項目）
        curriculum = []
        in_curriculum = False
        for l in lines2:
            if re.match(r"Lesson[\.\s]\d+.+\(\d+\)|Bonus\s+解鎖章節", l):
                in_curriculum = True
            if in_curriculum:
                if l in ("選購方案", "免費試看", "免費加值"):
                    break
                curriculum.append(l)
        result["curriculum"] = curriculum

        # 10 & 11. 講師名稱 & 介紹（lazy load，需捲動）
        page.evaluate(
            'var el = document.querySelector("#about-section-authors"); '
            'if(el) el.scrollIntoView();'
        )
        try:
            page.wait_for_selector("#about-section-authors h3", timeout=8000)
        except Exception:
            pass

        result["instructor_names"] = [
            el.inner_text().strip()
            for el in page.query_selector_all("#about-section-authors h3")
        ]
        result["instructor_descriptions"] = [
            el.inner_text().strip()
            for el in page.query_selector_all(
                "#about-section-authors .author-card-desc div"
            )
        ]

        # 12 & 13. 開課單位名稱 & 介紹
        try:
            idx = next(i for i, l in enumerate(lines2) if l == "開課單位")
            result["organizer_name"] = lines2[idx + 1] if idx + 1 < len(lines2) else None
            result["organizer_description"] = (
                lines2[idx + 2] if idx + 2 < len(lines2) else None
            )
        except StopIteration:
            result["organizer_name"] = None
            result["organizer_description"] = None

        # 14. 相關分類
        try:
            idx = next(i for i, l in enumerate(lines2) if l == "相關分類")
            categories = []
            for l in lines2[idx + 1 :]:
                # 遇到麵包屑導航（「首頁」開頭）就停
                if l == "首頁":
                    break
                categories.append(l)
            result["categories"] = categories
        except StopIteration:
            result["categories"] = []

        browser.close()
        return result
