# app.py
import json
import os
import sqlite3
import uuid
import hashlib
import inspect
from datetime import datetime
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backboard import BackboardClient

load_dotenv()

BB_API_KEY = os.getenv("BACKBOARD_API_KEY")
bb = BackboardClient(api_key=BB_API_KEY) if BB_API_KEY else None

FAST_PROVIDER = os.getenv("SB_FAST_PROVIDER", "google")
FAST_MODEL = os.getenv("SB_FAST_MODEL", "gemini-2.5-flash-lite")

REASON_PROVIDER = os.getenv("SB_REASON_PROVIDER", "google")
REASON_MODEL = os.getenv("SB_REASON_MODEL", "gemini-2.5-pro")

MEMORY_PROVIDER = os.getenv("SB_MEMORY_PROVIDER", "google")
MEMORY_MODEL = os.getenv("SB_MEMORY_MODEL", "gemini-2.5-flash-lite")

ActionType = Literal["EXPLAIN", "ARGUMENT", "VOTE", "ALIGN"]
VoteType = Literal["AGREE", "DISAGREE", "UNSURE"]

# Root app + mounted API (so frontend can call /api/*)
app = FastAPI(title="ShadowBrief (Local Mode)")
api = FastAPI(title="ShadowBrief API (Local Mode)")
app.mount("/api", api)

DB_PATH = os.getenv("SHADOWBRIEF_DB_PATH", "shadowbrief.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ---------------- Fixed topic ontology ----------------
FIXED_TOPICS = [
    "interest rates",
    "inflation",
    "monetary policy",
    "central bank independence",
    "banking system",
    "credit conditions",
    "equity markets",
    "bond markets",
    "precious metals",
    "commodities",
    "energy markets",
    "oil markets",
    "retail earnings",
    "tech earnings",
    "corporate earnings",
    "consumer spending",
    "labor market",
    "housing market",
    "fiscal policy",
    "public debt",
    "taxation",
    "trade",
    "geopolitics",
    "economic sanctions",
    "ai policy",
    "tech policy",
]

# ---------------- DB schema ----------------
cur.execute(
    """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  assistant_id TEXT NOT NULL
)
"""
)

cur.execute(
    """
CREATE TABLE IF NOT EXISTS threads (
  user_id TEXT NOT NULL,
  article_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  PRIMARY KEY (user_id, article_id)
)
"""
)

cur.execute(
    """
CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  topic TEXT NOT NULL,
  url TEXT,
  content TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
)
cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_time ON articles(created_at DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_topic_time ON articles(topic, created_at DESC)")

cur.execute(
    """
CREATE TABLE IF NOT EXISTS beliefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  stance TEXT NOT NULL,
  note TEXT,
  evidence TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
)

cur.execute(
    """
CREATE TABLE IF NOT EXISTS local_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT,
  content TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
)

cur.execute(
    """
CREATE TABLE IF NOT EXISTS llm_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  action TEXT NOT NULL,
  cache_key TEXT NOT NULL,
  response_json TEXT NOT NULL,
  model_name TEXT,
  llm_provider TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(thread_id, action, cache_key)
)
"""
)
cur.execute("CREATE INDEX IF NOT EXISTS idx_cache_thread_action ON llm_cache(thread_id, action, created_at DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_user_time ON beliefs(user_id, created_at DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_user_topic_time ON beliefs(user_id, topic, created_at DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_msgs_thread_time ON local_messages(thread_id, created_at DESC)")
conn.commit()

# Migration: add note column if missing (safe)
try:
    cur.execute("ALTER TABLE beliefs ADD COLUMN note TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass


def _add_col(sql: str):
    try:
        cur.execute(sql)
        conn.commit()
    except sqlite3.OperationalError:
        pass


# Belief enrichment columns (safe)
_add_col("ALTER TABLE beliefs ADD COLUMN belief_key TEXT")
_add_col("ALTER TABLE beliefs ADD COLUMN belief_text TEXT")
_add_col("ALTER TABLE beliefs ADD COLUMN confidence TEXT")
_add_col("ALTER TABLE beliefs ADD COLUMN conditions_json TEXT")
_add_col("ALTER TABLE beliefs ADD COLUMN claim TEXT")


def _safe_json(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        s = (s or "").strip()
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _safe_json_list(s: Optional[str]) -> list:
    if not s:
        return []
    try:
        s = (s or "").strip()
        obj = json.loads(s)
        return obj if isinstance(obj, list) else []
    except Exception:
        return []


def _mk_cache_key(parts: list[str]) -> str:
    h = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return h[:24]


class InitReq(BaseModel):
    user_id: str


class ThreadReq(BaseModel):
    user_id: str
    article_id: str


class IngestReq(BaseModel):
    title: str
    content: str
    url: Optional[str] = None


class IngestAndExplainReq(BaseModel):
    user_id: str
    title: str
    content: str
    url: Optional[str] = None


class ActionReq(BaseModel):
    user_id: str
    article_id: str
    action: ActionType
    content: Optional[str] = None
    vote: Optional[VoteType] = None
    topic: Optional[str] = None
    note: Optional[str] = None


def cache_get(thread_id: str, action: str, cache_key: str) -> Optional[dict]:
    row = cur.execute(
        """
        SELECT response_json, model_name, llm_provider, created_at
        FROM llm_cache
        WHERE thread_id=? AND action=? AND cache_key=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (thread_id, action, cache_key),
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["response_json"])
    except Exception:
        return None
    return {
        "data": data,
        "meta": {
            "model": row["model_name"],
            "provider": row["llm_provider"],
            "created_at": row["created_at"],
            "cache": "HIT",
        },
    }


def cache_put(thread_id: str, action: str, cache_key: str, payload: dict, provider: str, model: str) -> None:
    cur.execute(
        """
        INSERT OR REPLACE INTO llm_cache(thread_id, action, cache_key, response_json, model_name, llm_provider)
        VALUES (?,?,?,?,?,?)
        """,
        (thread_id, action, cache_key, json.dumps(payload, ensure_ascii=False), model, provider),
    )
    conn.commit()


def pick_model_for_action(action: str) -> tuple[str, str]:
    a = (action or "").upper()
    if a in {"EXPLAIN", "ARGUMENT", "TOPIC", "LEDGER"}:
        return FAST_PROVIDER, FAST_MODEL
    if a in {"MEMORY", "DISTILL_BELIEF", "BELIEF_ALERT"}:
        return MEMORY_PROVIDER, MEMORY_MODEL
    return FAST_PROVIDER, FAST_MODEL


async def get_or_create_assistant_backboard(user_id: str) -> str:
    row = cur.execute("SELECT assistant_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return row["assistant_id"]

    if not bb:
        raise RuntimeError("BACKBOARD_API_KEY not set")

    assistant = await bb.create_assistant(
        name=f"ShadowBrief ({user_id})",
        description="Extract arguments, handle challenges, and store user beliefs.",
    )
    assistant_id = str(assistant.assistant_id)

    cur.execute("INSERT INTO users(user_id, assistant_id) VALUES(?,?)", (user_id, assistant_id))
    conn.commit()
    return assistant_id


async def get_or_create_thread_backboard(user_id: str, article_id: str) -> str:
    row = cur.execute(
        "SELECT thread_id FROM threads WHERE user_id=? AND article_id=?",
        (user_id, article_id),
    ).fetchone()
    if row:
        return row["thread_id"]

    assistant_id = await get_or_create_assistant_backboard(user_id)
    thread = await bb.create_thread(assistant_id)
    thread_id = str(thread.thread_id)

    cur.execute(
        "INSERT INTO threads(user_id, article_id, thread_id) VALUES(?,?,?)",
        (user_id, article_id, thread_id),
    )
    conn.commit()
    return thread_id


async def get_ingest_thread_backboard() -> str:
    return await get_or_create_thread_backboard("__system__", "__ingest__")


def log_message(thread_id: str, role: str, content: str, action: Optional[str] = None) -> None:
    cur.execute(
        "INSERT INTO local_messages(thread_id, role, action, content) VALUES(?,?,?,?)",
        (thread_id, role, action, content),
    )
    conn.commit()


def get_thread_messages(thread_id: str, limit: int = 200) -> list[dict]:
    rows = cur.execute(
        """
        SELECT role, action, content, created_at
        FROM local_messages
        WHERE thread_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (thread_id, limit),
    ).fetchall()

    return list(
        reversed(
            [
                {"role": r["role"], "action": r["action"], "content": r["content"], "created_at": r["created_at"]}
                for r in rows
            ]
        )
    )


def db_get_article(article_id: str) -> Optional[sqlite3.Row]:
    return cur.execute(
        "SELECT id, title, topic, url, content, created_at FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()


def get_article_text(article_id: str, max_chars: int = 60000) -> str:
    row = db_get_article(article_id)
    if not row:
        return f"[Unknown article_id: {article_id}]"
    return (row["content"] or "")[:max_chars]


def fetch_recent_beliefs(user_id: str, limit: int = 20) -> list[dict]:
    rows = cur.execute(
        """
        SELECT id, topic, stance, note, evidence, created_at,
               belief_key, belief_text, confidence, conditions_json, claim
        FROM beliefs
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "topic": r["topic"],
                "stance": r["stance"],
                "note": r["note"],
                "evidence": _safe_json(r["evidence"]),
                "created_at": r["created_at"],
                "belief_key": r["belief_key"],
                "belief_text": r["belief_text"],
                "confidence": r["confidence"],
                "conditions": _safe_json_list(r["conditions_json"]),
                "claim": r["claim"],
            }
        )
    return out


def fetch_recent_beliefs_for_topic(user_id: str, topic: str, limit: int = 20) -> list[dict]:
    rows = cur.execute(
        """
        SELECT id, topic, stance, note, evidence, created_at,
               belief_key, belief_text, confidence, conditions_json, claim
        FROM beliefs
        WHERE user_id=? AND topic=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, topic, limit),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "topic": r["topic"],
                "stance": r["stance"],
                "note": r["note"],
                "evidence": _safe_json(r["evidence"]),
                "created_at": r["created_at"],
                "belief_key": r["belief_key"],
                "belief_text": r["belief_text"],
                "confidence": r["confidence"],
                "conditions": _safe_json_list(r["conditions_json"]),
                "claim": r["claim"],
            }
        )
    return out


async def bb_json(thread_id: str, prompt: str, action: str, cache_key: Optional[str] = None) -> tuple[dict, dict]:
    provider, model = pick_model_for_action(action)

    if not bb:
        raise RuntimeError("BACKBOARD_API_KEY not set")

    # -------- cache --------
    if cache_key:
        hit = cache_get(thread_id, action, cache_key)
        if hit:
            meta = hit["meta"] | {"cache": "HIT"}
            return hit["data"], meta

    def _extract_text(resp) -> str:
        if resp is None:
            return ""
        if isinstance(resp, dict):
            return str(resp.get("content") or resp.get("text") or resp.get("message") or "").strip()
        return str(
            getattr(resp, "content", None)
            or getattr(resp, "text", None)
            or getattr(resp, "message", None)
            or ""
        ).strip()

    def _strip_json_fences(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        # Remove ```json ... ``` or ``` ... ```
        if s.startswith("```"):
            # drop first fence line
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            # drop ending fence
            if s.rstrip().endswith("```"):
                s = s.rstrip()
                s = s[: -3]
            s = s.strip()

        # If model added extra text, try to slice the first {...} block
        if "{" in s and "}" in s:
            i = s.find("{")
            j = s.rfind("}")
            if i != -1 and j != -1 and j > i:
                s = s[i : j + 1].strip()
        return s

    async def run_once(p: str) -> str:
        # Prefer non-streaming
        try:
            resp = bb.add_message(
                thread_id=thread_id,
                content=p,
                llm_provider=provider,
                model_name=model,
                stream=False,
            )
            if inspect.iscoroutine(resp):
                resp = await resp
            text = _extract_text(resp)
            if text:
                return text
        except TypeError:
            pass
        except Exception:
            pass

        # Streaming fallback
        chunks: list[str] = []
        stream = bb.add_message(
            thread_id=thread_id,
            content=p,
            llm_provider=provider,
            model_name=model,
            stream=True,
        )
        if inspect.iscoroutine(stream):
            stream = await stream

        async for event in stream:
            if not isinstance(event, dict):
                continue
            et = event.get("type")
            if et == "content_streaming":
                chunks.append(event.get("content", "") or "")
            elif et in {"error", "exception"}:
                raise RuntimeError(f"Backboard stream error: {event}")

        return "".join(chunks).strip()

    def parse_or_raise(raw: str, tag: str) -> dict:
        raw = (raw or "").strip()
        cooked = _strip_json_fences(raw)
        if not cooked:
            raise RuntimeError(f"[{tag}] Empty LLM response after cleanup. provider={provider} model={model}")

        try:
            obj = json.loads(cooked)
        except Exception as e:
            preview = cooked[:700]
            raise RuntimeError(
                f"[{tag}] Invalid JSON from LLM after cleanup. provider={provider} model={model} "
                f"len={len(cooked)} preview={preview!r}"
            ) from e

        if not isinstance(obj, dict):
            raise RuntimeError(f"[{tag}] JSON was not an object. provider={provider} model={model} type={type(obj)}")
        return obj

    # -------- main call --------
    text1 = await run_once(prompt)
    try:
        out = parse_or_raise(text1, "FIRST")
    except Exception:
        repair = (
            "Output ONLY raw JSON with no markdown, no triple backticks, no prose.\n"
            "Return ONLY the JSON object.\n\n"
            "ORIGINAL INSTRUCTION:\n" + prompt
        )
        text2 = await run_once(repair)
        out = parse_or_raise(text2, "REPAIR")

    if cache_key:
        cache_put(thread_id, action, cache_key, out, provider, model)

    meta = {"provider": provider, "model": model, "cache": "MISS"}
    return out, meta


# ---------------- Topic classification (fixed list) ----------------
async def classify_topic(title: str, content: str) -> tuple[str, dict]:
    thread_id = await get_ingest_thread_backboard()

    sample = (content or "")[:6000]
    topic_list = ", ".join(FIXED_TOPICS)

    prompt = (
        "You MUST output ONLY valid JSON. No markdown. No extra text.\n"
        "Task: choose the SINGLE best topic from the allowed list.\n"
        'Return JSON: { "topic": string }\n'
        "Rules:\n"
        "- You MUST choose exactly one topic from the list below.\n"
        "- Do NOT invent new topics.\n"
        "- Choose the most general applicable topic.\n\n"
        f"ALLOWED TOPICS:\n{topic_list}\n\n"
        f"TITLE:\n{title}\n\n"
        f"CONTENT:\n{sample}"
    )

    ck = _mk_cache_key(["TOPIC_FIXED_V1", title.strip()[:200], sample[:2000]])
    out, meta = await bb_json(thread_id, prompt, "TOPIC", cache_key=ck)

    topic = str(out.get("topic") or "").strip().lower()
    if topic not in FIXED_TOPICS:
        topic = "equity markets"
    return topic, meta


# ---------------- Belief distillation + alert ----------------
async def distill_belief(topic: str, vote: str, claim: str, user_note: str) -> tuple[dict, dict]:
    thread_id = await get_ingest_thread_backboard()

    prompt = (
        "You MUST output ONLY valid JSON. No markdown.\n"
        "Task: convert the user's stance into a specific belief proposition that can recur across articles.\n"
        "Return JSON with keys:\n"
        '{ "belief_key": string, "belief_text": string, "confidence": "low"|"medium"|"high", '
        '"conditions": array of strings, "why_now": string }\n'
        "Rules:\n"
        "- belief_key: 2-6 words, lowercase, no names/dates.\n"
        "- belief_text: ONE durable sentence; avoid article-specific details.\n"
        "- conditions: 0-3 short conditions/assumptions.\n"
        "- why_now: one short sentence tying it to the current claim.\n"
        "- Do NOT just restate the topic.\n\n"
        f"TOPIC: {topic}\n"
        f"STANCE: {vote}\n"
        f"CLAIM: {claim}\n"
        f"USER_NOTE: {user_note or ''}\n"
    )

    ck = _mk_cache_key(["DISTILL_BELIEF_V1", topic, vote, (claim or "")[:400], (user_note or "")[:200]])
    out, meta = await bb_json(thread_id, prompt, "DISTILL_BELIEF", cache_key=ck)

    out["belief_key"] = str(out.get("belief_key") or "general").strip().lower()
    out["belief_text"] = str(out.get("belief_text") or claim or "").strip()
    out["confidence"] = str(out.get("confidence") or "medium").strip().lower()
    out["conditions"] = out.get("conditions") if isinstance(out.get("conditions"), list) else []
    out["why_now"] = str(out.get("why_now") or "").strip()

    if out["confidence"] not in {"low", "medium", "high"}:
        out["confidence"] = "medium"

    return out, meta


async def compare_beliefs_for_alert(topic: str, new_belief: dict, prior_beliefs: list[dict]) -> tuple[dict, dict]:
    thread_id = await get_ingest_thread_backboard()

    prior = []
    for b in (prior_beliefs or [])[:8]:
        prior.append(
            {
                "id": b.get("id"),
                "stance": b.get("stance"),
                "belief_key": b.get("belief_key"),
                "belief_text": (b.get("belief_text") or b.get("claim") or "")[:260],
                "created_at": b.get("created_at"),
            }
        )

    prompt = (
        "You MUST output ONLY valid JSON. No markdown.\n"
        "Task: decide if the NEW belief conflicts with any PRIOR belief on the SAME topic.\n"
        'Return JSON: { "type": "none"|"shift"|"conflict"|"duplicate"|"distinct", '
        '"message": string, "conflicts_with_id": number|null }\n'
        "Definitions:\n"
        "- duplicate: same proposition as a prior belief.\n"
        "- shift: same proposition but stance changed.\n"
        "- conflict: incompatible propositions OR stance contradicts a close equivalent.\n"
        "- distinct: different proposition (no issue).\n"
        "- none: no alert.\n"
        "Rules:\n"
        "- Only raise conflict/shift if fairly confident.\n"
        "- message should be 1–2 short sentences.\n\n"
        f"TOPIC: {topic}\n"
        f"NEW: {json.dumps(new_belief, ensure_ascii=False)}\n"
        f"PRIOR: {json.dumps(prior, ensure_ascii=False)}\n"
    )

    ck = _mk_cache_key(
        [
            "BELIEF_ALERT_V1",
            topic,
            (new_belief.get("belief_key") or "")[:80],
            (new_belief.get("belief_text") or "")[:200],
            (new_belief.get("stance") or "")[:10],
            json.dumps(prior, ensure_ascii=False)[:800],
        ]
    )
    out, meta = await bb_json(thread_id, prompt, "BELIEF_ALERT", cache_key=ck)

    t = str(out.get("type") or "none").strip().lower()
    if t not in {"none", "shift", "conflict", "duplicate", "distinct"}:
        t = "none"

    msg = str(out.get("message") or "").strip()
    cid = out.get("conflicts_with_id")
    try:
        cid = int(cid) if cid is not None else None
    except Exception:
        cid = None

    return {"type": t, "message": msg, "conflicts_with_id": cid}, meta


# ---------------- Ledger synthesis ----------------
async def synthesize_ledger_topic(user_id: str, topic: str, beliefs: list[dict]) -> tuple[dict, dict]:
    thread_id = await get_ingest_thread_backboard()

    items = []
    for b in (beliefs or [])[:40]:
        items.append(
            {
                "id": b.get("id"),
                "stance": b.get("stance"),
                "belief_text": (b.get("belief_text") or b.get("claim") or ""),
                "confidence": b.get("confidence") or None,
                "created_at": b.get("created_at"),
            }
        )

    latest_ts = (items[0].get("created_at") if items else "") or ""
    ck = _mk_cache_key(["LEDGER_V1", user_id, topic, str(len(items)), str(latest_ts)])

    prompt = (
        "You MUST output ONLY valid JSON. No markdown.\n"
        "Task: Synthesize the user's overall position for this TOPIC based on the belief list.\n"
        "Return JSON with EXACT keys:\n"
        '{'
        '"summary": string, '
        '"position_label": "leans agree"|"leans disagree"|"mixed/conditional"|"unclear", '
        '"confidence": "low"|"medium"|"high", '
        '"top_themes": array of strings, '
        '"drift": {"status":"stable"|"shifting"|"recently_changed","note":string}, '
        '"representative_belief_ids": array of numbers'
        "}\n"
        "Rules:\n"
        "- summary: 1–2 sentences.\n"
        "- top_themes: 3–5 short items.\n"
        "- representative_belief_ids: choose 2–4 ids from the list.\n"
        "- position_label MUST be one of the allowed strings.\n"
        "- confidence should reflect consistency + amount of evidence.\n\n"
        f"TOPIC: {topic}\n"
        f"BELIEFS (newest first):\n{json.dumps(items, ensure_ascii=False)}\n"
    )

    out, meta = await bb_json(thread_id, prompt, "LEDGER", cache_key=ck)

    pl = str(out.get("position_label") or "unclear").strip().lower()
    if pl not in {"leans agree", "leans disagree", "mixed/conditional", "unclear"}:
        pl = "unclear"

    conf = str(out.get("confidence") or "medium").strip().lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"

    drift = out.get("drift") if isinstance(out.get("drift"), dict) else {}
    ds = str((drift or {}).get("status") or "stable").strip().lower()
    if ds not in {"stable", "shifting", "recently_changed"}:
        ds = "stable"
    dn = str((drift or {}).get("note") or "").strip()

    ids = out.get("representative_belief_ids")
    if not isinstance(ids, list):
        ids = []
    rep_ids = []
    for x in ids[:6]:
        try:
            rep_ids.append(int(x))
        except Exception:
            pass

    themes = out.get("top_themes")
    if not isinstance(themes, list):
        themes = []
    themes = [str(t).strip() for t in themes if str(t).strip()][:6]

    return (
        {
            "summary": str(out.get("summary") or "").strip(),
            "position_label": pl,
            "confidence": conf,
            "top_themes": themes,
            "drift": {"status": ds, "note": dn},
            "representative_belief_ids": rep_ids,
        },
        meta,
    )


def seed_if_empty():
    row = cur.execute("SELECT COUNT(*) AS n FROM articles").fetchone()
    if row and int(row["n"]) == 0:
        aid = "a1"
        cur.execute(
            "INSERT OR IGNORE INTO articles(id, title, topic, url, content) VALUES (?,?,?,?,?)",
            (
                aid,
                "Why High Interest Rates Threaten Growth",
                "interest rates",
                None,
                (
                    "High interest rates can reduce investment by raising borrowing costs. "
                    "They can also cool consumer spending and housing demand. "
                    "However, the net effect depends on inflation expectations, labor markets, "
                    "and credit conditions across sectors."
                ),
            ),
        )
        conn.commit()


seed_if_empty()

# ===================== ROUTES =====================

@api.get("/health")
async def health():
    return {"ok": True, "mode": "local", "time": datetime.utcnow().isoformat() + "Z"}


@api.get("/articles")
async def list_articles():
    rows = cur.execute(
        "SELECT id, title, topic, created_at FROM articles ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    return {
        "data": [
            {"id": r["id"], "title": r["title"], "topic": r["topic"], "created_at": r["created_at"]}
            for r in rows
        ]
    }


@api.get("/articles/{article_id}")
async def get_article(article_id: str):
    r = db_get_article(article_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown article_id")
    return {
        "data": {
            "id": r["id"],
            "title": r["title"],
            "topic": r["topic"],
            "url": r["url"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
    }


@api.post("/articles/ingest")
async def ingest_article(req: IngestReq):
    title = (req.title or "").strip()
    content = (req.content or "").strip()
    url = (req.url or "").strip() or None

    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not content or len(content) < 80:
        raise HTTPException(status_code=400, detail="content is required (min ~80 chars)")

    topic, meta = await classify_topic(title, content)
    article_id = f"a_{uuid.uuid4().hex[:10]}"

    cur.execute(
        "INSERT INTO articles(id, title, topic, url, content) VALUES (?,?,?,?,?)",
        (article_id, title, topic, url, content),
    )
    conn.commit()

    return {
        "ok": True,
        "data": {"id": article_id, "title": title, "topic": topic, "url": url},
        "classifier": {"model": meta.get("model"), "provider": meta.get("provider"), "cache": meta.get("cache")},
    }


@api.post("/articles/ingest_and_explain")
async def ingest_and_explain(req: IngestAndExplainReq):
    user_id = (req.user_id or "").strip()
    title = (req.title or "").strip()
    content = (req.content or "").strip()
    url = (req.url or "").strip() or None

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not content or len(content) < 80:
        raise HTTPException(status_code=400, detail="content is required (min ~80 chars)")

    topic, meta_topic = await classify_topic(title, content)
    article_id = f"a_{uuid.uuid4().hex[:10]}"

    cur.execute(
        "INSERT INTO articles(id, title, topic, url, content) VALUES (?,?,?,?,?)",
        (article_id, title, topic, url, content),
    )
    conn.commit()

    thread_id = await get_or_create_thread_backboard(user_id, article_id)
    article_text = get_article_text(article_id, max_chars=12000)

    prompt = (
        "You MUST output ONLY valid JSON. No markdown. No extra commentary.\n"
        "Return STRICT JSON with keys:\n"
        "context: { issue: string, background: array of strings}\n"
        "argument: { thesis: string, reasons: array of strings, assumptions: array of strings }\n"
        "Rules:\n"
        "- Do NOT summarize.\n"
        "- Context is neutral orientation.\n"
        "- Argument reflects the author's position.\n"
        "- Keep bullets concise and have ideally 3 for reasons and 3 for assumptions.\n"
        f"\nARTICLE:\n{article_text}"
    )

    log_message(thread_id, role="user", action="EXPLAIN", content="EXPLAIN (auto) requested")
    ck = _mk_cache_key(["EXPLAIN_V1", article_id, article_text[:2000]])
    out, meta_explain = await bb_json(thread_id, prompt, "EXPLAIN", cache_key=ck)
    log_message(thread_id, role="assistant", action="EXPLAIN", content=json.dumps(out, ensure_ascii=False))

    return {
        "ok": True,
        "data": {"id": article_id, "title": title, "topic": topic, "url": url, "thread_id": thread_id},
        "classifier": {
            "model": meta_topic.get("model"),
            "provider": meta_topic.get("provider"),
            "cache": meta_topic.get("cache"),
        },
        "explain": {
            "context": out.get("context"),
            "argument": out.get("argument"),
            "model": meta_explain.get("model"),
            "provider": meta_explain.get("provider"),
            "cache": meta_explain.get("cache"),
        },
    }


@api.post("/init")
async def init(req: InitReq):
    assistant_id = await get_or_create_assistant_backboard(req.user_id)
    return {"assistant_id": assistant_id}


@api.post("/thread")
async def thread(req: ThreadReq):
    thread_id = await get_or_create_thread_backboard(req.user_id, req.article_id)
    return {"thread_id": thread_id}


@api.post("/action")
async def action(req: ActionReq):
    thread_id = await get_or_create_thread_backboard(req.user_id, req.article_id)

    # ---------------- VOTE ----------------
    if req.action == "VOTE":
        if req.vote is None:
            raise HTTPException(status_code=400, detail="vote is required for VOTE")

        topic = (req.topic or "equity markets").strip().lower()
        if topic not in FIXED_TOPICS:
            topic = "equity markets"

        claim = (req.content or "").strip()
        user_note = (req.note or "").strip()

        priors = fetch_recent_beliefs_for_topic(req.user_id, topic, limit=12)

        distilled, meta_mem = await distill_belief(topic, req.vote, claim, user_note)

        new_belief_obj = {
            "belief_key": distilled.get("belief_key"),
            "belief_text": distilled.get("belief_text"),
            "stance": req.vote,
        }

        alert, meta_alert = await compare_beliefs_for_alert(topic, new_belief_obj, priors)

        evidence_obj = {
            "article_id": req.article_id,
            "claim": claim or None,
            "why_now": distilled.get("why_now"),
            "memory_model": meta_mem.get("model"),
            "memory_provider": meta_mem.get("provider"),
            "memory_cache": meta_mem.get("cache"),
            "alert_type": alert.get("type"),
            "alert_conflicts_with_id": alert.get("conflicts_with_id"),
        }

        cur.execute(
            """
            INSERT INTO beliefs(
                user_id, topic, stance, note, evidence,
                belief_key, belief_text, confidence, conditions_json, claim
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                req.user_id,
                topic,
                req.vote,
                (user_note or None),
                json.dumps(evidence_obj, ensure_ascii=False),
                distilled.get("belief_key"),
                distilled.get("belief_text"),
                distilled.get("confidence"),
                json.dumps(distilled.get("conditions") or [], ensure_ascii=False),
                (claim or None),
            ),
        )
        conn.commit()

        msg = f"VOTE: {req.vote} (topic='{topic}')"
        if user_note and user_note.strip():
            msg += f" note='{user_note.strip()[:120]}'"
        log_message(thread_id, role="user", action="VOTE", content=msg)

        return {
            "action": "VOTE",
            "ok": True,
            "stored_vote": req.vote,
            "topic": topic,
            "thread_id": thread_id,
            "mode": "local",
            "belief_alert": alert,
            "belief_alert_meta": {
                "model": meta_alert.get("model"),
                "provider": meta_alert.get("provider"),
                "cache": meta_alert.get("cache"),
            },
        }

    # ---------------- ALIGN (Where you stand) ----------------
    if req.action == "ALIGN":
        if not req.content:
            raise HTTPException(status_code=400, detail="content is required for ALIGN")

        try:
            payload = json.loads(req.content)
        except Exception:
            payload = {}

        thesis = payload.get("thesis", "")
        belief_text = payload.get("belief_text", "")
        stance = payload.get("stance", "")

        prompt = (
            "You MUST output ONLY valid JSON. No markdown.\n"
            "Task: compare the article's thesis with the user's belief.\n"
            'Return JSON: { "position": "reinforces|contradicts|partially overlaps|unrelated", "summary": string }\n\n'
            f"ARTICLE_THESIS:\n{thesis}\n\n"
            f"USER_BELIEF:\n{belief_text}\n"
            f"(Stance: {stance})"
        )

        ck = _mk_cache_key(["ALIGN_V1", thesis[:200], belief_text[:200], stance])
        out, meta = await bb_json(thread_id, prompt, "ALIGN", cache_key=ck)

        log_message(thread_id, role="assistant", action="ALIGN", content=json.dumps(out, ensure_ascii=False))

        return {
            "action": "ALIGN",
            "ok": True,
            "thread_id": thread_id,
            "response": out,
            "model": meta.get("model"),
            "provider": meta.get("provider"),
            "cache": meta.get("cache"),
        }

    raise HTTPException(status_code=400, detail="unknown action")


@api.get("/messages")
async def messages(user_id: str, article_id: str, limit: int = 200):
    thread_id = await get_or_create_thread_backboard(user_id, article_id)
    return {"thread_id": thread_id, "mode": "local", "data": get_thread_messages(thread_id, limit=limit)}


@api.get("/beliefs")
async def beliefs(user_id: str, topic: Optional[str] = None, limit: int = 20):
    if topic:
        t = topic.strip().lower()
        data = fetch_recent_beliefs_for_topic(user_id, t, limit=limit)
    else:
        data = fetch_recent_beliefs(user_id, limit=limit)
    return {"user_id": user_id, "topic": topic, "data": data, "mode": "local"}


@api.get("/beliefs/latest")
async def latest_belief(user_id: str, topic: str):
    t = topic.strip().lower()
    row = cur.execute(
        """
        SELECT id, topic, stance, note, evidence, created_at,
               belief_key, belief_text, confidence, conditions_json, claim
        FROM beliefs
        WHERE user_id=? AND topic=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, t),
    ).fetchone()

    if not row:
        return {"user_id": user_id, "topic": t, "data": None, "mode": "local"}

    return {
        "user_id": user_id,
        "topic": t,
        "data": {
            "id": row["id"],
            "topic": row["topic"],
            "stance": row["stance"],
            "note": row["note"],
            "evidence": _safe_json(row["evidence"]),
            "created_at": row["created_at"],
            "belief_key": row["belief_key"],
            "belief_text": row["belief_text"],
            "confidence": row["confidence"],
            "conditions": _safe_json_list(row["conditions_json"]),
            "claim": row["claim"],
        },
        "mode": "local",
    }


@api.get("/ledger")
async def ledger(user_id: str, limit_per_topic: int = 40, min_count: int = 3):
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")

    out_rows = []

    for t in FIXED_TOPICS:
        beliefs = fetch_recent_beliefs_for_topic(uid, t, limit=min(limit_per_topic, 80))
        evidence_count = len(beliefs)
        last_updated = beliefs[0]["created_at"] if evidence_count else None

        if evidence_count < int(min_count):
            out_rows.append(
                {
                    "topic": t,
                    "enough_data": False,
                    "summary": "",
                    "position_label": "unclear",
                    "confidence": "low",
                    "evidence_count": evidence_count,
                    "last_updated": last_updated,
                    "drift": {"status": "stable", "note": ""},
                    "top_themes": [],
                    "representative_beliefs": [],
                }
            )
            continue

        synth, meta = await synthesize_ledger_topic(uid, t, beliefs)

        id_to_belief = {int(b["id"]): b for b in beliefs if b.get("id") is not None}
        rep = []
        for bid in synth.get("representative_belief_ids", [])[:4]:
            try:
                b = id_to_belief.get(int(bid))
            except Exception:
                b = None
            if b:
                rep.append(b)

        out_rows.append(
            {
                "topic": t,
                "enough_data": True,
                "summary": synth.get("summary", ""),
                "position_label": synth.get("position_label", "unclear"),
                "confidence": synth.get("confidence", "medium"),
                "evidence_count": evidence_count,
                "last_updated": last_updated,
                "drift": synth.get("drift", {"status": "stable", "note": ""}),
                "top_themes": synth.get("top_themes", []),
                "representative_beliefs": rep,
                "ledger_meta": {
                    "model": meta.get("model"),
                    "provider": meta.get("provider"),
                    "cache": meta.get("cache"),
                },
            }
        )

    return {"user_id": uid, "data": out_rows, "mode": "local"}
