from playwright.sync_api import sync_playwright
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
            result["content"] = content_el.inner_text().strip() if content_el else None

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
                imgs = page.query_selector_all("img")
                img_srcs = []
                seen = set()
                for img in imgs:
                    src = img.get_attribute("src") or ""
                    if (
                        src
                        and src not in seen
                        and "static.pressplay.cc" in src
                        and re.search(r"\.(jpg|jpeg|png|webp)", src, re.I)
                    ):
                        img_srcs.append(src)
                        seen.add(src)
                result["images"] = img_srcs

            # 9. 目錄 / 14. 相關分類（需點課程目錄 tab）
            need_curriculum_tab = need & {"curriculum", "categories"}
            lines2 = lines
            if need_curriculum_tab:
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

            if "curriculum" in need:
                # 展開所有章節手風琴（每個章節預設摺疊）
                for btn in page.query_selector_all(
                    "#about-section-public_articles button, "
                    "#about-section-public_articles [role=button]"
                ):
                    try:
                        if btn.get_attribute("aria-expanded") == "false":
                            btn.click()
                            page.wait_for_timeout(150)
                    except Exception:
                        pass
                page.wait_for_timeout(500)
                curriculum_el = page.query_selector(
                    "#about-section-public_articles > div > div:nth-child(2)"
                )
                result["curriculum"] = curriculum_el.inner_text().strip() if curriculum_el else ""

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

            # 14. 相關分類
            if "categories" in need:
                try:
                    idx = next(i for i, l in enumerate(lines2) if l == "相關分類")
                    categories = []
                    for l in lines2[idx + 1 :]:
                        if l == "首頁":
                            break
                        categories.append(l)
                    result["categories"] = categories
                except StopIteration:
                    result["categories"] = []

            return result

        finally:
            browser.close()
