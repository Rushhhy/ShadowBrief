// App.jsx
import React, { useEffect, useMemo, useState } from "react";
import "./App.css";

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }

  if (!res.ok) throw new Error(data?.detail || data?.error || `HTTP ${res.status}`);
  return data;
}

function prettyDate(s) {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s);
  return d.toLocaleString();
}

function extractLatestExplain(messages) {
  const arr = Array.isArray(messages) ? messages : [];
  for (let i = arr.length - 1; i >= 0; i--) {
    const m = arr[i];
    if (m?.role === "assistant" && m?.action === "EXPLAIN") {
      try {
        const obj = JSON.parse(m.content);
        return obj && typeof obj === "object" ? obj : null;
      } catch {
        return null;
      }
    }
  }
  return null;
}

function positionLabel(pos) {
  if (pos === "reinforces") return "Reinforces";
  if (pos === "contradicts") return "Contradicts";
  if (pos === "partially overlaps") return "Partially overlaps";
  if (pos === "unrelated") return "Unrelated";
  return "—";
}

function positionClass(pos) {
  if (pos === "reinforces") return "reinforces";
  if (pos === "contradicts") return "contradicts";
  if (pos === "partially overlaps") return "partially";
  if (pos === "unrelated") return "unrelated";
  return "unrelated";
}

const TOPIC_EMOJI = {
  "interest rates": "🏦",
  "inflation": "📈",
  "monetary policy": "🏛️",
  "central bank independence": "🛡️",
  "banking system": "🏦",
  "credit conditions": "💳",
  "equity markets": "📊",
  "bond markets": "🧾",
  "precious metals": "🥇",
  "commodities": "📦",
  "energy markets": "⚡",
  "oil markets": "🛢️",
  "retail earnings": "🛍️",
  "tech earnings": "💻",
  "corporate earnings": "🏢",
  "consumer spending": "🛒",
  "labor market": "👷",
  "housing market": "🏠",
  "fiscal policy": "💰",
  "public debt": "🏷️",
  "taxation": "🧾",
  "trade": "🚢",
  "geopolitics": "🌍",
  "economic sanctions": "⛔",
  "ai policy": "🤖",
  "tech policy": "📜",
};

const DEFAULT_TOPIC_EMOJI = "📌";

export default function App() {
  const [view, setView] = useState("article"); // "article" | "ledger"
  const [ledgerRows, setLedgerRows] = useState([]);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [ledgerErr, setLedgerErr] = useState("");
  const [ledgerExpandedTopic, setLedgerExpandedTopic] = useState(null);

  const [alignment, setAlignment] = useState(null);

  // keep internal
  const [userId] = useState("u1");

  const [articleId, setArticleId] = useState("");
  const [article, setArticle] = useState(null);
  const [topic, setTopic] = useState("");

  const [, setThreadId] = useState(null);
  const [messages, setMessages] = useState([]);

  const [context, setContext] = useState(null);
  const [argument, setArgument] = useState(null);

  const [voteFlash, setVoteFlash] = useState("");
  const [beliefAlert, setBeliefAlert] = useState(null);
  const [lastVote, setLastVote] = useState("");

  const [latestBelief, setLatestBelief] = useState(null);
  const [topicBeliefs, setTopicBeliefs] = useState([]);

  const [expandedId, setExpandedId] = useState(null);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const canQuery = userId.trim() && articleId.trim();
  const currentClaim = argument?.thesis || "";

  // Deep-link: /?article=a_xxx
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const aid = params.get("article");
    if (aid) setArticleId(aid);
  }, []);

  async function ensureThread() {
    await api("/init", { method: "POST", body: JSON.stringify({ user_id: userId }) });
    const t = await api("/thread", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, article_id: articleId }),
    });
    setThreadId(t.thread_id);
    return t.thread_id;
  }

  async function refreshLedger() {
    if (!userId.trim()) return;
    setLedgerErr("");
    setLedgerLoading(true);
    try {
      const r = await api(`/ledger?user_id=${encodeURIComponent(userId)}`);
      setLedgerRows(r.data || []);
    } catch (e) {
      setLedgerErr(String(e.message || e));
    } finally {
      setLedgerLoading(false);
    }
  }

  async function loadArticle(id) {
    if (!id) return;
    const r = await api(`/articles/${encodeURIComponent(id)}`);
    setArticle(r.data || null);
    setTopic((r.data?.topic || "").trim());
  }

  async function refreshMessages() {
    if (!canQuery) return;
    const r = await api(
      `/messages?user_id=${encodeURIComponent(userId)}&article_id=${encodeURIComponent(articleId)}`
    );

    setThreadId(r.thread_id);

    const msgs = r.data || [];
    setMessages(msgs);

    const ex = extractLatestExplain(msgs);
    setContext(ex?.context || null);
    setArgument(ex?.argument || null);
  }

  async function refreshLatestBelief(t) {
    if (!userId.trim() || !t) return;
    const r = await api(
      `/beliefs/latest?user_id=${encodeURIComponent(userId)}&topic=${encodeURIComponent(t.toLowerCase())}`
    );
    setLatestBelief(r.data || null);
  }

  async function refreshTopicBeliefs(t) {
    if (!userId.trim() || !t) return;
    const r = await api(
      `/beliefs?user_id=${encodeURIComponent(userId)}&topic=${encodeURIComponent(t.toLowerCase())}&limit=40`
    );
    setTopicBeliefs(r.data || []);
  }

  // When switching to ledger, load it
  useEffect(() => {
    if (view !== "ledger") return;
    refreshLedger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // Load article when articleId changes
  useEffect(() => {
    setErr("");
    setArgument(null);
    setContext(null);
    setVoteFlash("");
    setBeliefAlert(null);
    setAlignment(null);
    setExpandedId(null);
    setLastVote("");

    if (articleId) {
      loadArticle(articleId).catch((e) => setErr(String(e.message || e)));
    }
  }, [articleId]);

  // Ensure thread + pull messages
  useEffect(() => {
    if (!canQuery) return;

    (async () => {
      try {
        await ensureThread();
        await refreshMessages();
      } catch (e) {
        setErr(String(e.message || e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId]);

  // Beliefs when topic changes
  useEffect(() => {
    if (!topic) return;
    refreshLatestBelief(topic).catch(() => {});
    refreshTopicBeliefs(topic).catch(() => {});
  }, [topic]);

  // Reset alignment when argument changes
  useEffect(() => {
    setAlignment(null);
  }, [argument]);

  // Auto ALIGN
  useEffect(() => {
    if (!argument?.thesis) return;
    if (!latestBelief) return;
    if (!latestBelief?.belief_text && !latestBelief?.claim) return;

    let cancelled = false;

    (async () => {
      try {
        const r = await api("/action", {
          method: "POST",
          body: JSON.stringify({
            user_id: userId,
            article_id: articleId,
            action: "ALIGN",
            content: JSON.stringify({
              thesis: argument.thesis,
              belief_text: latestBelief.belief_text || latestBelief.claim || "",
              stance: latestBelief.stance || "",
            }),
          }),
        });

        if (!cancelled) setAlignment(r.response || null);
      } catch {
        // silent
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [argument, latestBelief, articleId, userId]);

  const timeline = useMemo(() => {
    const arr = Array.isArray(topicBeliefs) ? [...topicBeliefs] : [];
    arr.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    return arr;
  }, [topicBeliefs]);

  async function doVote(vote) {
    if (!currentClaim) return;

    setErr("");
    setLoading(true);
    try {
      await ensureThread();

      const r = await api("/action", {
        method: "POST",
        body: JSON.stringify({
          user_id: userId,
          article_id: articleId,
          action: "VOTE",
          vote,
          topic: topic || "equity markets",
          content: currentClaim || null,
          note: null,
        }),
      });

      setLastVote(vote);

      setVoteFlash(
        vote === "AGREE"
          ? "Saved: you agree."
          : vote === "DISAGREE"
          ? "Saved: you disagree."
          : "Saved: you’re unsure."
      );

      setBeliefAlert(r?.belief_alert || null);

      await refreshLatestBelief(topic);
      await refreshTopicBeliefs(topic);
      await refreshMessages();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  // Auto-clear vote flash
  useEffect(() => {
    if (!voteFlash) return;
    const t = setTimeout(() => setVoteFlash(""), 1800);
    return () => clearTimeout(t);
  }, [voteFlash]);

  const TopBar = (
    <div className="topbar">
      <div className="brand">
        <img src="/shadowbrief-icon.png" alt="ShadowBrief logo" className="brandIcon" />
        <h1>{view === "ledger" ? "ShadowBrief Ledger" : "ShadowBrief"}</h1>
      </div>

      <div className="topActions">
        {view === "ledger" ? (
          <button className="topBtn" onClick={() => setView("article")}>
            Back to Article
          </button>
        ) : (
          <button className="topBtn" onClick={() => setView("ledger")}>
            Ledger
          </button>
        )}
      </div>
    </div>
  );

  // Landing (no article id) — still allow Ledger access
  if (!articleId && view !== "ledger") {
    return (
      <div className="wrap">
        {TopBar}

        <div className="card cardAccent" style={{ marginTop: 12 }}>
          <div className="k">Extension-first</div>
          <div className="muted" style={{ marginTop: 8 }}>
            Open an article and click the ShadowBrief extension icon. That click performs the analysis.
          </div>
          <div className="spinnerRow">
            <span className="spinner" aria-hidden="true" />
            <span className="muted">Analyzing</span>
          </div>
          {err && <div className="err">Error: {err}</div>}
        </div>
      </div>
    );
  }

  const alignmentPos = alignment?.position || "";
  const posCls = positionClass(alignmentPos);
  const posLabel = positionLabel(alignmentPos);

  // Ledger view
  if (view === "ledger") {
    return (
      <div className="wrap">
        {TopBar}

        <div className="stack" style={{ marginTop: 12 }}>
          {ledgerLoading ? (
            <div className="card">
              <div className="muted">Loading ledger…</div>
            </div>
          ) : null}

          {(ledgerRows || []).map((row) => {
            const expanded = ledgerExpandedTopic === row.topic;
            const pos = row.position_label || "unclear";
            const conf = row.confidence || "low";
            const drift = row?.drift?.status || "stable";

            return (
              <div
                key={row.topic}
                className="card"
                onClick={() => setLedgerExpandedTopic(expanded ? null : row.topic)}
                role="button"
                tabIndex={0}
              >
                <div className="headerRow">
                  <div className="headerTitle">
                    <span style={{ marginRight: 10, opacity: 0.9 }}>
                      {TOPIC_EMOJI[(row.topic || "").toLowerCase()] || DEFAULT_TOPIC_EMOJI}
                    </span>
                    {row.topic}
                  </div>

                    <div className="ledgerChips">
                      {(() => {
                        const confRaw = (row.confidence || "low").toLowerCase();
                        const conf = ["low", "medium", "high"].includes(confRaw) ? confRaw : "low";
                        const confLabel = conf.charAt(0).toUpperCase() + conf.slice(1);

                        return (
                          <span className={`pill conviction ${conf}`}>
                            Conviction: {confLabel}
                          </span>
                        );
                      })()}

                      <span className="pill">
                        {row.evidence_count || 0} votes
                      </span>
                    </div>

                </div>


                <div className="muted" style={{ marginTop: 8 }}>
                  Last updated: {prettyDate(row.last_updated)}
                </div>

                {!row.enough_data ? (
                  <div className="muted" style={{ marginTop: 10 }}>
                    Not enough data yet — add {Math.max(0, 3 - (row.evidence_count || 0))} more vote(s).
                  </div>
                ) : (
                  <div className="muted" style={{ marginTop: 10 }}>
                    {row.summary}
                  </div>
                )}

                {expanded && row.enough_data ? (
                  <div style={{ marginTop: 14 }}>
                    {row?.drift?.note ? (
                      <div className="callout" style={{ marginBottom: 12 }}>
                        <div className="k" style={{ marginBottom: 6 }}>
                          Drift
                        </div>
                        <div className="muted">{row.drift.note}</div>
                      </div>
                    ) : null}

                    {Array.isArray(row.top_themes) && row.top_themes.length ? (
                      <div className="section">
                        <div className="k">Top themes</div>
                        <ul>
                          {row.top_themes.map((t, i) => (
                            <li key={i}>{t}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {Array.isArray(row.representative_beliefs) && row.representative_beliefs.length ? (
                      <div className="section">
                        <div className="k">Representative beliefs</div>
                        {row.representative_beliefs.map((b) => {
                          const stanceCls = String(b.stance || "").toLowerCase();
                          const beliefText = b.belief_text || b.claim || "";
                          return (
                            <div key={b.id} className="beliefItem" style={{ cursor: "default" }}>
                              <div className="beliefMetaRow">
                                <div className="beliefMetaLeft">
                                  <span className={`stance ${stanceCls}`}>{b.stance}</span>
                                  {b.confidence ? <span className="muted">{b.confidence}</span> : null}
                                  {b.belief_key ? <span className="muted">· {b.belief_key}</span> : null}
                                </div>
                                <div className="muted" style={{ fontSize: 12 }}>
                                  {prettyDate(b.created_at)}
                                </div>
                              </div>
                              <div className="beliefText expanded">{beliefText}</div>
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Article view
  return (
    <div className="wrap">
      {TopBar}

      {/* Article header */}
      <div className="card cardAccent" style={{ marginTop: 14 }}>
        <div className="headerRow">
          <div className="headerTitle">{article?.title || "(loading…)"}</div>
          <span className="pill pillBig">{topic || "—"}</span>
        </div>

        <div className="headerSubRow">
          {article?.url ? (
            <a href={article.url} target="_blank" rel="noreferrer">
              open original
            </a>
          ) : null}
        </div>
      </div>

      <div className="main2col">
        {/* LEFT COLUMN */}
        <div className="stack leftCol">
          {/* Vote bar */}
          <div className="card cardPrimaryAction">
            <div className="headerRow">
              <div className="k" style={{ marginBottom: 0 }}>
                Save your stance on this article’s claim
              </div>
              <span className="primaryBadge">Primary action</span>
            </div>

            <div className="muted" style={{ marginTop: 10 }}>
              {currentClaim ? (
                <>
                  Claim: <b>{currentClaim}</b>
                </>
              ) : (
                <>Waiting for analysis…</>
              )}
            </div>

            <div className="segmented">
              <button
                className={`segBtn ${lastVote === "AGREE" ? "active" : ""}`}
                disabled={loading || !currentClaim}
                onClick={() => doVote("AGREE")}
              >
                Agree
              </button>
              <button
                className={`segBtn ${lastVote === "DISAGREE" ? "active" : ""}`}
                disabled={loading || !currentClaim}
                onClick={() => doVote("DISAGREE")}
              >
                Disagree
              </button>
              <button
                className={`segBtn ${lastVote === "UNSURE" ? "active" : ""}`}
                disabled={loading || !currentClaim}
                onClick={() => doVote("UNSURE")}
              >
                Unsure
              </button>
            </div>

            {voteFlash ? <div className="toast">{voteFlash}</div> : null}

            {beliefAlert && beliefAlert.type && beliefAlert.type !== "none" ? (
              <div className="callout" style={{ marginTop: 12 }}>
                <div className="k" style={{ marginBottom: 6 }}>
                  {beliefAlert.type === "conflict"
                    ? "Possible conflict"
                    : beliefAlert.type === "shift"
                    ? "Mind-change?"
                    : beliefAlert.type === "duplicate"
                    ? "Duplicate belief"
                    : "Note"}
                </div>

                <div className="muted" style={{ whiteSpace: "pre-wrap" }}>
                  {beliefAlert.message || "This belief relates to your prior beliefs on this topic."}
                </div>
              </div>
            ) : null}
          </div>

          {/* Bottom row */}
          <div className="bottomGrid">
            <div className="card cardFill">
              <h2>Argument</h2>
              <div className="cardScroll">
                {argument ? (
                  <>
                    <div className="section">
                      <div className="k">Claim</div>
                      <div>{argument.thesis}</div>
                    </div>

                    <div className="section">
                      <div className="k">Reasons</div>
                      <ul>
                        {(argument.reasons || []).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="section">
                      <div className="k">Assumptions</div>
                      <ul>
                        {(argument.assumptions || []).map((a, i) => (
                          <li key={i}>{a}</li>
                        ))}
                      </ul>
                    </div>

                    {context?.stakeholders?.length ? (
                      <div className="section">
                        <div className="k">Stakeholders</div>
                        <ul>
                          {context.stakeholders.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="muted">Analysis not available yet.</div>
                )}
              </div>
            </div>

            <div className="card cardFill">
              <h2>Where you stand</h2>
              <div className="cardScroll">
                {alignment ? (
                  <>
                    <div className="section">
                      <div className="k">Position</div>
                      <div className={`posChip ${posCls}`}>{posLabel}</div>
                    </div>

                    <div className="section" style={{ whiteSpace: "pre-wrap" }}>
                      {alignment.summary}
                    </div>
                  </>
                ) : argument && latestBelief ? (
                  <div className="muted">Comparing article with your belief…</div>
                ) : (
                  <div className="muted">Alignment will appear once you have both an analysis and a belief.</div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="card cardFill beliefCard">
          <div className="headerRow">
            <div className="headerTitle">
              Belief History for <b>{topic || "—"}</b>
            </div>
          </div>

          <div className="beliefPanel cardScroll" style={{ marginTop: 12 }}>
            {timeline.length ? (
              timeline.slice(0, 80).map((b) => {
                const isExpanded = expandedId === b.id;
                const beliefText = b.belief_text || b.claim || "";
                const stanceCls = String(b.stance || "").toLowerCase();

                return (
                  <div
                    key={b.id}
                    className="beliefItem"
                    onClick={() => setExpandedId(isExpanded ? null : b.id)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="beliefMetaRow">
                      <div className="beliefMetaLeft">
                        <span className={`stance ${stanceCls}`}>{b.stance}</span>
                        {b.confidence ? <span className="muted">{b.confidence}</span> : null}
                        {b.belief_key ? <span className="muted">· {b.belief_key}</span> : null}
                      </div>

                      <div className="muted" style={{ fontSize: 12 }}>
                        {prettyDate(b.created_at)}
                      </div>
                    </div>

                    {beliefText ? (
                      <div className={`beliefText ${isExpanded ? "expanded" : ""}`}>{beliefText}</div>
                    ) : (
                      <div className="muted" style={{ marginTop: 10 }}>
                        (No text)
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="muted">
                No belief history yet for <b>{topic || "this topic"}</b>.
              </div>
            )}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="muted" style={{ marginTop: 10 }}>
          Loading…
        </div>
      ) : null}

      {err ? (
        <div className="err" style={{ marginTop: 10 }}>
          Error: {err}
        </div>
      ) : null}
    </div>
  );
}
