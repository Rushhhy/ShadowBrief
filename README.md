# ShadowBrief

ShadowBrief is a local-first application for **understanding news articles and tracking how your beliefs evolve over time**.

Instead of passively consuming news, ShadowBrief extracts the core argument of an article, lets you record your stance (agree / disagree / unsure), and aggregates those stances into a **Belief Ledger** that summarizes what you believe, by topic, and how strongly.

---

## What ShadowBrief Does

### 1. Article Understanding
- Ingests news articles
- Extracts the author’s **central argument** (thesis, reasoning, assumptions)
- Presents the argument clearly before you react to it

### 2. Belief Capture
- One-click voting: **Agree / Disagree / Unsure**
- Each vote is stored as a durable belief tied to a topic
- Designed to be fast and frictionless

### 3. Belief History
- View past beliefs per topic
- See how your stance has changed across different articles
- Click into individual beliefs for context

### 4. Belief Ledger
- One row per predefined topic (e.g. inflation, interest rates, geopolitics)
- Shows:
  - **Conviction** (Low / Medium / High)
  - **Vote count** (evidence)
- Conviction reflects internal consistency of beliefs, **not correctness**

---

## Why This Exists

News consumption is easy.  
Tracking how your beliefs form, stabilize, or drift is not.

ShadowBrief is built around a simple idea:
> *If you never record your beliefs, you can’t audit them later.*

The Belief Ledger makes belief formation explicit, inspectable, and revisable.

---

## Tech Stack

**Backend**
- FastAPI
- SQLite (local-first storage)
- Deterministic topic system
- LLM response caching

**Frontend**
- React (Vite)
- Minimal, information-dense UI
- Clear separation between article view and ledger view

**LLM Routing**
- Backboard (multi-provider support)
- Models can be swapped without changing application logic
