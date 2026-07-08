from playwright.sync_api import sync_playwright
from markdownify import markdownify as md
import re


def scrape_ppa_article(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("h1", timeout=90000)

            result = {}

            el = page.query_selector("h1")
            result["title"] = el.inner_text().strip() if el else None

            try:
                page.wait_for_selector(".pp-article-content", timeout=15000)
            except Exception:
                pass

            content_el = page.query_selector(".pp-article-content")
            html = content_el.inner_html() if content_el else None
            if html:
                raw_md = md(html, heading_style="ATX", bullets="-").strip()
                raw_md = '\n'.join(ln.rstrip() for ln in raw_md.split('\n'))
                # 移出粗體結尾的全形標點，避免 CommonMark 強調規則導致 ** 無法渲染
                raw_md = re.sub(r"\*\*([^*\n]+?)([：，、。！？；])\*\*", r"**\1**\2", raw_md)
                result["content"] = re.sub(r"\n{3,}", "\n\n", raw_md)
            else:
                result["content"] = None

            links = []
            if content_el:
                for a in content_el.query_selector_all("a"):
                    href = a.get_attribute("href") or ""
                    text = a.inner_text().strip()
                    if href and text:
                        links.append({"text": text, "url": href})
            result["links"] = links

            body = page.inner_text("body")
            m = re.search(r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})", body)
            result["publish_date"] = m.group(1) if m else None

            return result
        finally:
            browser.close()
def scrape_ppa_course(url: str, fields: list) -> dict:
    need = set(fields)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("h1", timeout=90000)

            result = {}

            # 1. 課程名稱
            if "title" in need:
                el = page.query_selector("h1")
                result["title"] = el.inner_text().strip() if el else None

            body = page.inner_text("body")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            # 2. 評價（星數）
            if "rating" in need:
                m = re.search(r"(\d+\.\d+)\s*評價", body)
                result["rating"] = m.group(1) if m else None

            # 3. 學習人數
            if "student_count" in need:
                m = re.search(r"([\d,]+)\s*人學習", body)
                result["student_count"] = m.group(1) if m else None

            # 4. 課程總覽（取最長的描述段落）
            if "overview" in need:
                try:
                    idx = next(i for i, l in enumerate(lines) if l == "課程總覽")
                    candidates = lines[idx + 1 : idx + 10]
                    result["overview"] = max(candidates, key=len)
                except StopIteration:
                    result["overview"] = None

            # 5. 你可以學到（lazy load，需捲動）
            if "what_you_learn" in need:
                page.evaluate(
                    'var el = document.querySelector("#about-section-summary_learning"); '
                    'if(el) el.scrollIntoView();'
                )
                page.wait_for_timeout(800)
                el = page.query_selector(
                    "#about-section-summary_learning > div > div.about-section-content > "
                    "div > div > div.expand-section > div > div"
                )
                if not el:
                    el = page.query_selector("#about-section-summary_learning")
                result["what_you_learn"] = (
                    el.text_content().strip().replace("\xa0", " ") if el else None
                )

            # 6. 誰適合學習（lazy load，需捲動）
            if "target_audience" in need:
                page.evaluate(
                    'var el = document.querySelector("#about-section-summary_suitable_for"); '
                    'if(el) el.scrollIntoView();'
                )
                page.wait_for_timeout(800)
                el = page.query_selector(
                    "#about-section-summary_suitable_for > div > div.about-section-content > "
                    "div > div > div.expand-section > div"
                )
                if not el:
                    el = page.query_selector("#about-section-summary_suitable_for")
                result["target_audience"] = (
                    el.text_content().strip().replace("\xa0", " ") if el else None
                )

            # 7. 價錢
            if "price" in need:
                el = page.query_selector(
                    "#about-section-side > div > div.purchase-info > "
                    "div.purchase-info-price-container > div > span"
                )
                result["price"] = el.inner_text().strip() if el else None

            # 8. 介紹裡的圖片網址（展開「更多介紹」）
            if "images" in need:
                for btn in page.query_selector_all(".pp-button-secondary"):
                    if "更多介紹" in btn.inner_text():
                        btn.click()
                        page.wait_for_timeout(1500)
                        break
                # 介紹區圖片放在 .pp-lightbox 的 data-src，頁面一渲染就有值，
                # 不受 lazy-load（src 在滾動前是空的）影響，也能避開下方輪播的重複圖。
                boxes = page.query_selector_all('.pp-lightbox[data-group="Pictures"]')
                img_srcs = []
                seen = set()
                for box in boxes:
                    src = box.get_attribute("data-src") or ""
                    if (
                        src
                        and src not in seen
                        and "static.pressplay.cc" in src
                        and re.search(r"\.(jpg|jpeg|png|webp|gif)", src, re.I)
                    ):
                        img_srcs.append(src)
                        seen.add(src)
                result["images"] = img_srcs

            # 9. 目錄（curriculum）— about 頁內嵌的「目錄與試看」區塊
            #    章節格式各課不一（章節一／第一章／第一章節／引言／Lesson…），
            #    直接抓區塊文字最穩，不靠格式 regex。
            if "curriculum" in need:
                curriculum = ""
                page.evaluate(
                    'var el = document.querySelector("#about-section-public_articles"); '
                    'if(el) el.scrollIntoView();'
                )
                page.wait_for_timeout(600)
                sec = page.query_selector("#about-section-public_articles")
                if sec:
                    # 展開「顯示全部章節 (N)」，可能需點多次。
                    # 注意：click handler 綁在內層 .pp-button-secondary，
                    # 點外層 .expand-section-button 不會觸發。
                    for _ in range(6):
                        target = None
                        for b in sec.query_selector_all(
                            ".expand-section-button .pp-button-secondary"
                        ):
                            try:
                                if "顯示全部章節" in b.inner_text():
                                    target = b
                                    break
                            except Exception:
                                pass
                        if not target:
                            break
                        try:
                            target.evaluate("el => el.click()")
                            page.wait_for_timeout(700)
                        except Exception:
                            break
                    # 章節內容放在各 .book-info 區塊；上方可能有「全部內容」試看輪播
                    # （.section-block swiper），只取 .book-info 可避免預覽字幕混入。
                    blocks = sec.query_selector_all(".book-info")
                    if blocks:
                        raw = "\n".join(b.inner_text() for b in blocks).strip()
                    else:
                        raw = sec.inner_text().strip()
                    skip = {"免費試看", "免費加值", "試看", "免費", "全部內容", "目錄與試看"}
                    lines_c = [
                        l.strip()
                        for l in raw.split("\n")
                        if l.strip()
                        and not l.strip().startswith("顯示全部章節")
                        and l.strip() not in skip
                    ]
                    curriculum = "\n".join(lines_c)
                result["curriculum"] = curriculum

            # 10 & 11. 講師名稱 & 介紹（lazy load，需捲動）
            if need & {"instructor_names", "instructor_descriptions"}:
                page.evaluate(
                    'var el = document.querySelector("#about-section-authors"); '
                    'if(el) el.scrollIntoView();'
                )
                try:
                    page.wait_for_selector("#about-section-authors h3", timeout=8000)
                except Exception:
                    pass

                if "instructor_names" in need:
                    result["instructor_names"] = [
                        el.inner_text().strip()
                        for el in page.query_selector_all("#about-section-authors h3")
                    ]
                if "instructor_descriptions" in need:
                    result["instructor_descriptions"] = [
                        el.inner_text().strip()
                        for el in page.query_selector_all(
                            "#about-section-authors .author-card-desc div"
                        )
                    ]

            # 12 & 13. 開課單位名稱 & 介紹（lazy load，需捲動）
            if need & {"organizer_name", "organizer_description"}:
                page.evaluate(
                    'var el = document.querySelector("#about-section-groups"); '
                    'if(el) el.scrollIntoView();'
                )
                try:
                    page.wait_for_selector(
                        "#about-section-groups .group-card-container h3", timeout=8000
                    )
                except Exception:
                    pass

                if "organizer_name" in need:
                    el = page.query_selector(
                        "#about-section-groups > div > div.about-section-content > div > div > "
                        "div > div > div.group-card > div.group-card-container > h3"
                    )
                    result["organizer_name"] = el.inner_text().strip() if el else None

                if "organizer_description" in need:
                    el = page.query_selector(
                        "#about-section-groups > div > div.about-section-content > div > div > "
                        "div > div > div.group-card > div.group-card-container > "
                        "div.group-card-desc > div"
                    )
                    result["organizer_description"] = el.inner_text().strip() if el else None

            # 14. 相關分類（#about-section-category 區塊，需捲動觸發 lazy load）
            if "categories" in need:
                page.evaluate(
                    'var el = document.querySelector("#about-section-category"); '
                    'if(el) el.scrollIntoView();'
                )
                page.wait_for_timeout(500)
                categories = []
                sec = page.query_selector("#about-section-category")
                if sec:
                    content = sec.query_selector(".about-section-content") or sec
                    for l in content.inner_text().split("\n"):
                        l = l.strip()
                        if l and l != "相關分類":
                            categories.append(l)
                result["categories"] = categories

            return result

        finally:
            browser.close()

