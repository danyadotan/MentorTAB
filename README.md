# MentorTAB

AI companion for **FIRST Israel robotics mentors** — plus a reusable community
group agent. One engine, powered by Claude, two faces.

- **MentorTAB — "Coaching Moment"** — free-text situation in → a structured,
  research-informed response out (what's happening / 5-minute move / long-term /
  research source). For mentors who are engineers, not therapists.
- **Talbot group agent** — memory, search, classification and matchmaking for a
  WhatsApp-style community group (e.g. the FIRST-parents registration bot).

Concept, product & clinical framing by **Danya Dotan**, Bridge-iT Technologies.

## Coaching guardrails (prompt + code)

A FIRST mentor is **not a therapist, not a babysitter, not a schoolteacher**.
The engine always assumes the real room — kids arrive tired/hungry after school
(state before content), ~half didn't choose to be there (build buy-in, not
assume it), and many on both sides are introverts (low-social-load moves). It
never diagnoses, and routes real risk to a responsible adult.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...

# live web server (coaching page + group widget)
TALBOT_PROFILE=first_robotics uvicorn server:app --port 8000
#  GET /mentortab  → live Coaching Moment page
#  POST /coach     → {"situation": "..."} → structured coaching JSON
#  GET /, POST /chat, POST /ingest, GET /profiles, GET /health

# coaching from the terminal
python coach.py "חבר צוות נסגר ומסרב לדבר יום לפני התחרות"

# group agent (CLI)
python talbot.py --list-profiles
python talbot.py --profile first_robotics --seed-demo
```

## Deploy (Render / Railway — recommended over Vercel for this FastAPI app)

`render.yaml`, `Procfile`, and `Dockerfile` are included. On Render: New →
Blueprint → point at this repo → set `ANTHROPIC_API_KEY` → deploy. Then open
`/mentortab`.

## WhatsApp bridge (optional, for the group agent)

```bash
cd whatsapp-bridge && npm install
GROUP_NAME="הורים | רובוטיקה FIRST" npm start   # scan QR from a DEDICATED phone
```
whatsapp-web.js is against WhatsApp ToS — use a dedicated number, or port to
Telegram's official Bot API (server side unchanged).

## Layout
```
coach.py            coaching engine (the MentorTAB core)
server.py           FastAPI: /coach + /mentortab + group endpoints
web/mentortab.html  live coaching UI
talbot.py storage.py profile.py tools.py   group agent
profiles/*.json     swappable community profiles
whatsapp-bridge/    WhatsApp connector
Dockerfile Procfile render.yaml .env.example   deploy
```
