# ShadowBrief

ShadowBrief is a browser extension + local app for **understanding news articles and tracking how your beliefs evolve over time**.

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

## User Flow
**Article 1**
<img width="1919" height="910" alt="Screenshot 2026-01-14 235317" src="https://github.com/user-attachments/assets/fb335034-5a4e-4e95-a8c1-840ea9030b2c" />
Extract the claim of the article and wait for user stance. User input's Agree, which gets saved in Belief History for the topic (trade)
<img width="1919" height="909" alt="Screenshot 2026-01-14 235407" src="https://github.com/user-attachments/assets/ab08e389-0a0d-4f88-9db7-8198109f1a35" />
**Article 2**
<img width="1919" height="908" alt="Screenshot 2026-01-14 235510" src="https://github.com/user-attachments/assets/40ba1e51-23f2-40b3-bd5b-23f58a90106e" />
Article 2 presents a claim that is contradictory to the user's previously saved stance (in Article 1). The contradiction is shown in the "Where you stand" section. 
<img width="1919" height="911" alt="Untitled" src="https://github.com/user-attachments/assets/38db7bda-41a7-4a61-aaad-8add5bae874a" />
User agrees to contradictory proposition and is alerted of a possible conflict.

**Belief Ledger - Trade section**
<img width="1919" height="910" alt="Screenshot 2026-01-15 000040" src="https://github.com/user-attachments/assets/b0070eee-dfb2-4d59-9fa6-887d4140dde2" />
The user's belief is summarized, whether they are consistent or not. A drift in beliefs is detected due to the contradictory stances.

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
