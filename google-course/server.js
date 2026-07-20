'use strict';

const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;
const BASE = '/google-course';
const MODEL = process.env.OPENAI_MODEL || 'gpt-4.1-mini';
const OPENAI_KEY = process.env.OPENAI_API_KEY || '';

app.disable('x-powered-by');
app.use(express.json({ limit: '32kb' }));

// 讓 Traefik / Cloudflare 後面拿得到真實 client IP
app.set('trust proxy', true);

const PUBLIC = path.join(__dirname, 'public');
const router = express.Router();

// 五篇文章：/google-course/day-1 ~ day-5（不帶 .html）
router.get('/day-:n(\\d)', (req, res) => {
  res.sendFile(path.join(PUBLIC, 'day-' + req.params.n + '.html'), (err) => {
    if (err) res.status(404).send('Not found');
  });
});

// 目錄頁
router.get('/', (req, res) => {
  res.sendFile(path.join(PUBLIC, 'index.html'));
});

// 名詞解釋後端代理：金鑰只留在伺服器，瀏覽器看不到
const WINDOW_MS = 60 * 1000;
const MAX_PER_WINDOW = 20;
const hits = new Map();

function rateLimited(ip) {
  const now = Date.now();
  const arr = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  arr.push(now);
  hits.set(ip, arr);
  if (hits.size > 5000) {
    for (const [k, v] of hits) if (!v.length || now - v[v.length - 1] > WINDOW_MS) hits.delete(k);
  }
  return arr.length > MAX_PER_WINDOW;
}

router.post('/api/explain', async (req, res) => {
  if (!OPENAI_KEY) {
    return res.status(500).json({ error: '伺服器未設定 OPENAI_API_KEY' });
  }
  const ip = req.ip || 'unknown';
  if (rateLimited(ip)) {
    return res.status(429).json({ error: '查詢太頻繁，請稍候再試' });
  }

  const b = req.body || {};
  const clip = (s, n) => String(s == null ? '' : s).slice(0, n);
  const term = clip(b.term, 400).trim();
  const title = clip(b.title, 200);
  const head = clip(b.head, 200);
  const para = clip(b.para, 4000);
  if (!term) return res.status(400).json({ error: '缺少要解釋的文字' });

  const sys =
    '你是一位專業的繁體中文技術編輯，服務台灣讀者。讀者正在閱讀一篇技術文章，選取了一段看不懂的文字。' +
    '請根據提供的上下文，用台灣慣用的說法解釋它的意思，讓讀者能接著讀下去。\n' +
    '規則：用繁體中文；3 到 5 句話，簡潔清楚；必要時舉一個具體例子或比喻；' +
    '若是專有名詞，說明它是什麼、在這個脈絡中扮演什麼角色；保留原文中的英文技術名詞不要硬翻；' +
    '不要使用破折號；只輸出解釋本身，不要客套話或前言。';
  const user =
    '文章標題：' + title + '\n所在章節：' + head + '\n\n該段落全文：\n' + para +
    '\n\n讀者看不懂的部分：「' + term + '」\n\n請解釋這部分的意思。';

  try {
    const r = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + OPENAI_KEY },
      body: JSON.stringify({
        model: MODEL,
        temperature: 0.3,
        messages: [
          { role: 'system', content: sys },
          { role: 'user', content: user },
        ],
      }),
    });
    if (!r.ok) {
      const t = await r.text();
      return res.status(502).json({ error: 'OpenAI 回應錯誤 (HTTP ' + r.status + ')', detail: t.slice(0, 220) });
    }
    const j = await r.json();
    const answer = (j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content || '').trim();
    return res.json({ answer, model: MODEL });
  } catch (err) {
    return res.status(502).json({ error: '呼叫 OpenAI 失敗', detail: String(err).slice(0, 220) });
  }
});

app.use(BASE, router);

// 靜態資源（圖片等，如果有的話）掛在 BASE 底下
app.use(BASE, express.static(PUBLIC));

app.get('/health', (req, res) => res.send('ok'));

app.listen(PORT, () => {
  console.log('google-course listening on ' + PORT + ', base ' + BASE);
});
