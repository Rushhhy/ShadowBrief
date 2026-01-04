import os
import sqlite3
from fastapi import FastAPI
from pydantic import BaseModel
from backboard import BackboardClient
from dotenv import load_dotenv
from pydantic import ValidationError
load_dotenv()

app = FastAPI()
client = BackboardClient(api_key=os.environ["BACKBOARD_API_KEY"])

# --- tiny sqlite mapping ---
conn = sqlite3.connect("shadowbrief.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  assistant_id TEXT NOT NULL
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS threads (
  user_id TEXT NOT NULL,
  article_url TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  PRIMARY KEY (user_id, article_url)
)""")
conn.commit()

class InitReq(BaseModel):
    user_id: str

class ThreadReq(BaseModel):
    user_id: str
    article_url: str

class MsgReq(BaseModel):
    user_id: str
    article_url: str
    content: str

async def get_or_create_assistant(user_id: str) -> str:
    row = cur.execute("SELECT assistant_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return row[0]

    assistant = await client.create_assistant(
        name="ShadowBrief",
        description="A news context assistant that learns the user's macro preferences over time."
    )  # create_assistant exists in SDK :contentReference[oaicite:6]{index=6}

    cur.execute(
        "INSERT INTO users(user_id, assistant_id) VALUES(?,?)",
        (user_id, str(assistant.assistant_id))
    )

    conn.commit()
    return assistant.assistant_id

async def get_or_create_thread(user_id: str, article_url: str) -> str:
    row = cur.execute(
        "SELECT thread_id FROM threads WHERE user_id=? AND article_url=?",
        (user_id, article_url)
    ).fetchone()
    if row:
        return row[0]

    assistant_id = await get_or_create_assistant(user_id)
    thread = await client.create_thread(assistant_id)  # create_thread exists :contentReference[oaicite:7]{index=7}

    cur.execute(
        "INSERT INTO threads(user_id, article_url, thread_id) VALUES(?,?,?)",
        (user_id, article_url, str(thread.thread_id))
    )

    conn.commit()
    return thread.thread_id

@app.post("/init")
async def init(req: InitReq):
    assistant_id = await get_or_create_assistant(req.user_id)
    return {"assistant_id": assistant_id}

@app.post("/thread")
async def thread(req: ThreadReq):
    thread_id = await get_or_create_thread(req.user_id, req.article_url)
    return {"thread_id": thread_id}

@app.post("/message")
async def message(req: MsgReq):
    thread_id = await get_or_create_thread(req.user_id, req.article_url)

    try:
        resp = await client.add_message(
            thread_id=thread_id,
            content=req.content,
            memory="Auto",
            stream=False
        )
        return {"reply": resp.latest_message.content}
    except ValidationError:
        thread = await client.get_thread(thread_id)
        return {"thread_dump": thread.model_dump()}


