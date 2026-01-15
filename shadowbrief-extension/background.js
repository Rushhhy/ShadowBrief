const API_BASE = "http://127.0.0.1:8000/api";
const UI_BASE = "http://localhost:5173";
const USER_ID = "u1";

// Promise wrappers (MV3 consistency)
function tabsCreate(createProps) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create(createProps, (tab) => {
      const err = chrome.runtime.lastError;
      if (err) return reject(err);
      resolve(tab);
    });
  });
}

function tabsUpdate(tabId, updateProps) {
  return new Promise((resolve, reject) => {
    chrome.tabs.update(tabId, updateProps, (tab) => {
      const err = chrome.runtime.lastError;
      if (err) return reject(err);
      resolve(tab);
    });
  });
}

function buildExtractionScript() {
  return () => {
    function clean(s) {
      return String(s || "").replace(/\s+/g, " ").replace(/\u00a0/g, " ").trim();
    }

    function getTitle() {
      const og = document.querySelector('meta[property="og:title"]')?.content;
      return clean(og || document.title || "");
    }

    function getMainText() {
      const candidates = [document.querySelector("article"), document.querySelector("main"), document.body].filter(Boolean);
      const junkSelectors = [
        "nav","header","footer","aside","form","button","input","script","style","noscript",
        "[role=banner]","[role=navigation]","[role=contentinfo]","[aria-modal=true]",
      ];

      for (const el of candidates) {
        const clone = el.cloneNode(true);
        for (const sel of junkSelectors) clone.querySelectorAll(sel).forEach((n) => n.remove());

        const blocks = Array.from(clone.querySelectorAll("p, h1, h2, h3, li, blockquote"))
          .map((n) => clean(n.innerText))
          .filter((t) => t.length >= 30);

        const text = blocks.join("\n");
        if (text.length >= 800) return text;
      }

      return clean(document.body?.innerText || "");
    }

    return { title: getTitle(), content: getMainText() };
  };
}

async function ingestAndExplain({ title, content, url }) {
  const resp = await fetch(`${API_BASE}/articles/ingest_and_explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, title, url, content }),
  });

  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }

  if (!resp.ok) throw new Error(data?.detail || data?.error || `HTTP ${resp.status}`);
  return data;
}

async function handleClick(tab) {
  if (!tab?.id) return;

  const u = tab.url || "";
  if (u.startsWith("chrome://") || u.startsWith("edge://") || u.startsWith("about:")) return;

  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: buildExtractionScript(),
  });

  const title = (result?.title || "").trim() || "Untitled";
  const content = (result?.content || "").trim();

  const MAX_CHARS = 120000;
  const capped = content.length > MAX_CHARS ? content.slice(0, MAX_CHARS) : content;

  // Open UI immediately
  const loadingUrl =
    `${UI_BASE}/?loading=1` +
    `&user=${encodeURIComponent(USER_ID)}` +
    `&title=${encodeURIComponent(title)}` +
    `&url=${encodeURIComponent(tab.url || "")}`;

  const uiTab = await tabsCreate({ url: loadingUrl });

  try {
    const r = await ingestAndExplain({ title, content: capped, url: tab.url || null });

    const articleId = r?.data?.id;
    if (!articleId) throw new Error("No article id returned from backend");

    const target =
      `${UI_BASE}/?article=${encodeURIComponent(articleId)}` +
      `&user=${encodeURIComponent(USER_ID)}`;

    await tabsUpdate(uiTab.id, { url: target });
  } catch (e) {
    const errUrl = `${UI_BASE}/?error=${encodeURIComponent(String(e.message || e))}`;
    await tabsUpdate(uiTab.id, { url: errUrl });
  }
}

chrome.action.onClicked.addListener((tab) => {
  handleClick(tab).catch(() => {});
});
