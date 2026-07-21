'use strict';

const express = require('express');
const path = require('path');
const { Pool } = require('pg');

const app = express();
const PORT = process.env.PORT || 3000;
// 對外路徑是 /google-course，但 Coolify 的 Traefik 會 StripPrefix 掉這段，
// 容器內部實際收到的是根路徑，所以 app 一律掛在 '/'。
const MODEL = process.env.OPENAI_MODEL || 'gpt-4.1-mini';
const OPENAI_KEY = process.env.OPENAI_API_KEY || '';

app.disable('x-powered-by');
app.use(express.json({ limit: '32kb' }));

// 讓 Traefik / Cloudflare 後面拿得到真實 client IP
app.set('trust proxy', true);

// ---- Postgres（記錄查詢與回饋，best-effort，連不上也不影響頁面）----
let pool = null;
if (process.env.DATABASE_URL) {
  pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: false, max: 4 });
  pool.on('error', (e) => console.error('[pg] pool error:', e.message));
  (async () => {
    try {
      await pool.query(`
        CREATE TABLE IF NOT EXISTS explain_log (
          id BIGSERIAL PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          url TEXT,
          day TEXT,
          title TEXT,
          section TEXT,
          term TEXT,
          context TEXT,
          answer TEXT,
          model TEXT,
          feedback TEXT
        )`);
      // 舊表補欄位（新表已含，這行對舊表才有作用）
      await pool.query('ALTER TABLE explain_log ADD COLUMN IF NOT EXISTS url TEXT');
      // 翻譯問題回報（反白按倒讚）
      await pool.query(`
        CREATE TABLE IF NOT EXISTS translation_report (
          id BIGSERIAL PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          url TEXT,
          day TEXT,
          title TEXT,
          section TEXT,
          term TEXT,
          context TEXT
        )`);
      console.log('[pg] explain_log / translation_report 就緒');
    } catch (e) {
      console.error('[pg] 建表失敗，將以無資料庫模式運作:', e.message);
    }
  })();
} else {
  console.log('[pg] 未設定 DATABASE_URL，略過資料庫記錄');
}

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

// ---- 簡易 IP 限流 ----
const WINDOW_MS = 60 * 1000;
const MAX_PER_WINDOW = 30;
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

// 名詞解釋後端代理：金鑰只留在伺服器，瀏覽器看不到
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
  const url = clip(b.url, 500) || null;
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

    // 寫入資料庫（best-effort），成功則回傳 id 供回饋回寫
    let id = null;
    if (pool) {
      try {
        const day = (title.match(/Day\s*([1-5])/) || [])[1] || null;
        const ins = await pool.query(
          'INSERT INTO explain_log(url,day,title,section,term,context,answer,model) VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id',
          [url, day, title, head, term, para, answer, MODEL]
        );
        id = ins.rows[0].id;
      } catch (e) {
        console.error('[pg] insert 失敗:', e.message);
      }
    }
    return res.json({ answer, model: MODEL, id });
  } catch (err) {
    return res.status(502).json({ error: '呼叫 OpenAI 失敗', detail: String(err).slice(0, 220) });
  }
});

// 回饋回寫：up / down
router.post('/api/feedback', async (req, res) => {
  if (!pool) return res.json({ ok: false });
  const ip = req.ip || 'unknown';
  if (rateLimited(ip)) return res.status(429).json({ ok: false });
  const b = req.body || {};
  const id = b.id;
  const value = b.value;
  if (!id || (value !== 'up' && value !== 'down')) {
    return res.status(400).json({ error: '參數錯誤' });
  }
  try {
    const upd = await pool.query('UPDATE explain_log SET feedback=$1 WHERE id=$2', [value, String(id)]);
    if (upd.rowCount === 0) return res.status(404).json({ ok: false, error: '找不到該筆紀錄' });
    return res.json({ ok: true });
  } catch (e) {
    console.error('[pg] feedback 失敗:', e.message);
    return res.status(500).json({ ok: false });
  }
});

// 翻譯問題回報：讀者反白後按倒讚，記下這段可能有問題的翻譯（不呼叫 AI）
router.post('/api/report', async (req, res) => {
  const ip = req.ip || 'unknown';
  if (rateLimited(ip)) return res.status(429).json({ ok: false, error: '太頻繁，請稍後再試' });
  const b = req.body || {};
  const clip = (s, n) => String(s == null ? '' : s).slice(0, n);
  const term = clip(b.term, 400).trim();
  if (!term) return res.status(400).json({ ok: false, error: '缺少回報的文字' });
  const url = clip(b.url, 500) || null;
  const title = clip(b.title, 200);
  const head = clip(b.head, 200);
  const para = clip(b.para, 4000);
  if (!pool) return res.json({ ok: false });
  try {
    const day = (title.match(/Day\s*([1-5])/) || [])[1] || null;
    const ins = await pool.query(
      'INSERT INTO translation_report(url,day,title,section,term,context) VALUES($1,$2,$3,$4,$5,$6) RETURNING id',
      [url, day, title, head, term, para]
    );
    return res.json({ ok: true, id: ins.rows[0].id });
  } catch (e) {
    console.error('[pg] report insert 失敗:', e.message);
    return res.status(500).json({ ok: false });
  }
});

// 唯讀統計（token 保護）：內網 DB 無法對外連線，用這支讀回資料
router.get('/api/_admin/log', async (req, res) => {
  const tok = process.env.ADMIN_TOKEN;
  if (!tok || req.query.token !== tok) return res.status(404).send('Not found');
  if (!pool) return res.status(503).json({ error: '未啟用資料庫' });
  const limit = Math.min(parseInt(req.query.limit, 10) || 50, 500);
  try {
    const total = await pool.query(
      `SELECT count(*)::int AS n,
              count(*) FILTER (WHERE feedback='up')::int AS up,
              count(*) FILTER (WHERE feedback='down')::int AS down,
              count(*) FILTER (WHERE feedback IS NULL)::int AS none
       FROM explain_log`
    );
    const rows = await pool.query(
      `SELECT id,
              to_char(created_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS') AS created_at,
              url, day, title, term, section,
              context, answer, model, feedback
       FROM explain_log ORDER BY id DESC LIMIT $1`,
      [limit]
    );
    return res.json({ stats: total.rows[0], rows: rows.rows });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// 翻譯問題回報清單（token 保護）
router.get('/api/_admin/reports', async (req, res) => {
  const tok = process.env.ADMIN_TOKEN;
  if (!tok || req.query.token !== tok) return res.status(404).send('Not found');
  if (!pool) return res.status(503).json({ error: '未啟用資料庫' });
  const limit = Math.min(parseInt(req.query.limit, 10) || 50, 500);
  try {
    const total = await pool.query('SELECT count(*)::int AS n FROM translation_report');
    const rows = await pool.query(
      `SELECT id,
              to_char(created_at AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS') AS created_at,
              url, day, title, term, section, context
       FROM translation_report ORDER BY id DESC LIMIT $1`,
      [limit]
    );
    return res.json({ stats: total.rows[0], rows: rows.rows });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// 清空紀錄（token 保護，且需帶確認字串）：供測試後歸零或日後重來
router.post('/api/_admin/reset', async (req, res) => {
  const tok = process.env.ADMIN_TOKEN;
  if (!tok || (req.body && req.body.token) !== tok) return res.status(404).send('Not found');
  if (!pool) return res.status(503).json({ error: '未啟用資料庫' });
  if (!req.body || req.body.confirm !== 'DELETE-ALL') {
    return res.status(400).json({ error: '需帶 confirm:"DELETE-ALL"' });
  }
  try {
    await pool.query('TRUNCATE explain_log, translation_report RESTART IDENTITY');
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

// 只刪測試標記列（term 以 ZZTEST 開頭），供驗證後清理，不動真實資料
router.post('/api/_admin/purge_tests', async (req, res) => {
  const tok = process.env.ADMIN_TOKEN;
  if (!tok || (req.body && req.body.token) !== tok) return res.status(404).send('Not found');
  if (!pool) return res.status(503).json({ error: '未啟用資料庫' });
  try {
    const r1 = await pool.query("DELETE FROM explain_log WHERE term LIKE 'ZZTEST%'");
    const r2 = await pool.query("DELETE FROM translation_report WHERE term LIKE 'ZZTEST%'");
    return res.json({ ok: true, deleted: r1.rowCount + r2.rowCount });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

app.use('/', router);

// 靜態資源（圖片等，如果有的話）
app.use('/', express.static(PUBLIC));

app.get('/health', (req, res) => res.send('ok'));

app.listen(PORT, () => {
  console.log('google-course listening on ' + PORT);
});
