const express = require('express');
const { chromium } = require('playwright');

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.post('/scrape', async (req, res) => {
  const { url, selector } = req.body;

  if (!url || !selector) {
    return res.status(400).json({ error: 'url and selector are required' });
  }

  let browser;
  try {
    browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });

    const exists = await page.$(selector);
    if (!exists) {
      return res.status(404).json({ error: 'selector not found on page' });
    }

    const content = await page.$eval(selector, el => {
      el.querySelectorAll('a').forEach(a => {
        const href = a.href;
        const text = a.textContent.trim();
        if (href && text) {
          a.textContent = `[${text}](${href})`;
        }
      });
      return el.innerText;
    });

    res.json({ content });
  } catch (err) {
    res.status(500).json({ error: err.message });
  } finally {
    if (browser) await browser.close();
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`scraper-api running on port ${PORT}`));
