"""FastAPI server for the MentorTAB coaching engine + Talbot group agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from coach import CoachEngine
from profile import Profile, list_profiles
from storage import add_message, init_db
from talbot import TalbotAgent

WEB_DIR = Path(__file__).parent / "web"
MAX_SESSIONS = 200
MAX_HISTORY_MESSAGES = 40

app = FastAPI(title="MentorTAB API", version="1.1")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("TALBOT_CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])

_profile: Optional[Profile] = None
_sessions: dict[str, TalbotAgent] = {}
_coach: Optional[CoachEngine] = None


def get_profile() -> Profile:
    global _profile
    if _profile is None:
        _profile = Profile.load_by_name(os.environ.get("TALBOT_PROFILE", "first_robotics"))
        init_db()
    return _profile


def get_agent(session_id: str) -> TalbotAgent:
    agent = _sessions.get(session_id)
    if agent is None:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        try:
            agent = TalbotAgent(get_profile())
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        _sessions[session_id] = agent
    return agent


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


class ChatResponse(BaseModel):
    reply: str
    session_id: str


class IngestRequest(BaseModel):
    sender_name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    category: Optional[str] = None
    sender_phone: Optional[str] = None
    timestamp: Optional[str] = None


class CoachRequest(BaseModel):
    situation: str = Field(min_length=1, max_length=4000)
    intake: Optional[dict] = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "profile": get_profile().name}


@app.get("/profiles")
def profiles() -> dict:
    return {"active": get_profile().name, "available": list_profiles()}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    agent = get_agent(req.session_id)
    if len(agent.history) > MAX_HISTORY_MESSAGES:
        agent.history = agent.history[-MAX_HISTORY_MESSAGES:]
        while agent.history and agent.history[0]["role"] != "user":
            agent.history.pop(0)
    try:
        reply = agent.chat(req.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent error: {exc}")
    return ChatResponse(reply=reply, session_id=req.session_id)


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    profile = get_profile()
    category = req.category if req.category in profile.category_keys else "general"
    msg_id = add_message(sender_name=req.sender_name, content=req.content, category=category,
                         sender_phone=req.sender_phone, timestamp=req.timestamp)
    return {"ok": True, "id": msg_id, "category": category}


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
def widget() -> str:
    return WIDGET_HTML
