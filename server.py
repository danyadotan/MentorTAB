"""FastAPI server for the MentorTAB coaching engine + Talbot group agent."""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from coach import CoachEngine
from profile import Profile, list_profiles
from storage import add_message, adopt_legacy_rows, init_db
from talbot import TalbotAgent

WEB_DIR = Path(__file__).parent / "web"
MAX_SESSIONS = 200
MAX_HISTORY_MESSAGES = 40

app = FastAPI(title="MentorTAB API", version="1.2")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("TALBOT_CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])

_profiles: dict[str, Profile] = {}
_sessions: dict[tuple[str, str, bool], TalbotAgent] = {}
_legacy_adopted = False
_coach: Optional[CoachEngine] = None


def default_profile_key() -> str:
    return os.environ.get("TALBOT_PROFILE", "first_robotics")


def get_profile(key: Optional[str] = None) -> Profile:
    """Load (and cache) a class profile. One server serves every profile in profiles/."""
    key = key or default_profile_key()
    if key not in _profiles:
        if key not in list_profiles():
            raise HTTPException(status_code=404, detail=f"Unknown class '{key}'. Available: {list_profiles()}")
        _profiles[key] = Profile.load_by_name(key)
        init_db()
        global _legacy_adopted
        if not _legacy_adopted:
            adopt_legacy_rows(default_profile_key())
            _legacy_adopted = True
    return _profiles[key]


def bridge_authorized(token: Optional[str]) -> bool:
    """True only for the WhatsApp bridge, which sends the shared BRIDGE_TOKEN.

    Group memory (reading and writing) is limited to the bridge, so the public
    web page can neither read a group's messages nor plant fake ones.
    """
    expected = os.environ.get("BRIDGE_TOKEN", "")
    # Compare as bytes: compare_digest rejects non-ASCII str (e.g. a Hebrew password).
    return bool(expected) and token is not None and hmac.compare_digest(token.encode(), expected.encode())


def get_agent(session_id: str, profile: Profile, memory: bool) -> TalbotAgent:
    slot = (profile.key, session_id, memory)
    agent = _sessions.get(slot)
    if agent is None:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        try:
            agent = TalbotAgent(profile, memory=memory)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        _sessions[slot] = agent
    return agent


def _is_plain_user_turn(msg: dict) -> bool:
    return msg.get("role") == "user" and isinstance(msg.get("content"), str)


def trim_history(history: list[dict]) -> list[dict]:
    """Keep the tail of a conversation, starting on a real user turn.

    A naive cut can land between an assistant tool_use and its tool_result,
    which the API rejects; so drop leading messages until a plain user text turn.
    """
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    tail = history[-MAX_HISTORY_MESSAGES:]
    while tail and not _is_plain_user_turn(tail[0]):
        tail.pop(0)
    return tail


def get_coach() -> CoachEngine:
    global _coach
    if _coach is None:
        try:
            _coach = CoachEngine()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    return _coach


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="default", max_length=128)
    profile: Optional[str] = Field(default=None, max_length=64, description="Class key, e.g. 'hiphop'")


class ChatResponse(BaseModel):
    reply: str
    session_id: str


class IngestRequest(BaseModel):
    sender_name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    category: Optional[str] = None
    sender_phone: Optional[str] = None
    timestamp: Optional[str] = None
    profile: Optional[str] = Field(default=None, max_length=64, description="Class key, e.g. 'hiphop'")


class CoachRequest(BaseModel):
    situation: str = Field(min_length=1, max_length=4000)
    intake: Optional[dict] = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "profile": get_profile().name, "default_class": default_profile_key(),
            "classes": list_profiles()}


@app.get("/profiles")
def profiles() -> dict:
    return {"active": get_profile().name, "default": default_profile_key(), "available": list_profiles()}


@app.get("/profile-info")
def profile_info(cls: Optional[str] = Query(default=None, alias="class")) -> dict:
    """Title + suggested questions for a class's Desk page."""
    profile = get_profile(cls)
    return {
        "key": profile.key,
        "name": profile.name,
        "display_name": profile.display_name or profile.name,
        "suggested_questions": profile.suggested_questions,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_bridge_token: Optional[str] = Header(default=None)) -> ChatResponse:
    # Only the authenticated WhatsApp bridge gets the group's memory; the web page (no token) answers
    # from the class knowledge alone. A wrong token fails loudly so a misconfigured bridge is noticed.
    if x_bridge_token is not None and not bridge_authorized(x_bridge_token):
        raise HTTPException(status_code=401, detail="Invalid bridge token (check BRIDGE_TOKEN on the server).")
    agent = get_agent(req.session_id, get_profile(req.profile), memory=x_bridge_token is not None)
    agent.history = trim_history(agent.history)
    try:
        reply = agent.chat(req.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent error: {exc}")
    return ChatResponse(reply=reply, session_id=req.session_id)


@app.post("/ingest")
def ingest(req: IngestRequest, x_bridge_token: Optional[str] = Header(default=None)) -> dict:
    if not os.environ.get("BRIDGE_TOKEN"):
        raise HTTPException(status_code=503, detail="Group memory is off: set BRIDGE_TOKEN on the server.")
    if not bridge_authorized(x_bridge_token):
        raise HTTPException(status_code=401, detail="Invalid bridge token.")
    profile = get_profile(req.profile)
    category = req.category if req.category in profile.category_keys else "general"
    msg_id = add_message(sender_name=req.sender_name, content=req.content, category=category,
                         sender_phone=req.sender_phone, timestamp=req.timestamp, group_id=profile.key)
    return {"ok": True, "id": msg_id, "class": profile.key, "category": category}


@app.post("/coach")
def coach(req: CoachRequest) -> dict:
    engine = get_coach()
    try:
        return engine.coach(req.situation, req.intake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Coach error: {exc}")


@app.get("/mentortab", response_class=HTMLResponse)
def mentortab_page():
    path = WEB_DIR / "mentortab.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="mentortab.html not found")
    return FileResponse(path)


@app.get("/desk", response_class=HTMLResponse)
def desk_page():
    path = WEB_DIR / "desk.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="desk.html not found")
    return FileResponse(path)


WIDGET_HTML = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Talbot</title>
<style>body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:#eef2ee;color:#1b241f;display:flex;justify-content:center;padding:24px 12px}
.box{width:100%;max-width:480px;background:#fff;border:1px solid #d8dfd8;border-radius:14px;display:flex;flex-direction:column;height:80vh;overflow:hidden}
.hd{background:#0f5c46;color:#fff;padding:12px 16px;font-weight:600}.log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px;background:#e2ded3}
.m{max-width:85%;padding:8px 12px;border-radius:10px;font-size:.9rem;white-space:pre-wrap}.u{background:#d7f5cf;align-self:flex-end}.b{background:#eaf2fb;align-self:flex-start}
form{display:flex;gap:8px;padding:10px;border-top:1px solid #d8dfd8}input{flex:1;border:1px solid #d8dfd8;border-radius:999px;padding:9px 14px;font:inherit}
button{background:#1667a8;color:#fff;border:none;border-radius:999px;padding:9px 18px;font:inherit;cursor:pointer}</style></head><body>
<div class="box"><div class="hd">טלבוט</div><div class="log" id="log"></div>
<form id="f"><input id="q" placeholder="שאלו אותי משהו..." autocomplete="off"><button id="send">שלח</button></form></div>
<script>const log=document.getElementById('log'),form=document.getElementById('f'),input=document.getElementById('q'),send=document.getElementById('send');
const sid='web-'+Math.random().toString(36).slice(2,10);
function add(c,t){const d=document.createElement('div');d.className='m '+c;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
form.addEventListener('submit',async e=>{e.preventDefault();const t=input.value.trim();if(!t)return;input.value='';send.disabled=true;add('u',t);const w=add('b','...');
try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,session_id:sid})});const d=await r.json();w.textContent=r.ok?d.reply:('שגיאה: '+(d.detail||r.status));}catch(err){w.textContent='שגיאת רשת: '+err.message;}
send.disabled=false;input.focus();});</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    """Root serves the MentorTAB coaching page so the base URL is the real product."""
    path = WEB_DIR / "mentortab.html"
    if not path.exists():
        return WIDGET_HTML
    return FileResponse(path)


@app.get("/widget", response_class=HTMLResponse)
def widget() -> str:
    return WIDGET_HTML

