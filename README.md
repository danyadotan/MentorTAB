# MentorTAB

**One platform, two products** — an AI companion for FIRST Israel robotics, built on a single profile-driven, research-grounded, privacy-first engine.

Concept, product & clinical framing by **Danya Dotan**, Bridge-iT Technologies.

## 🧭 MentorTAB · Coaching — for mentors
Research-grounded support at the behavioral moment of need. A mentor describes a real moment; MentorTAB reframes it and returns one move: what's likely happening, what to do in 5 minutes, what to build long-term, and the research source.

**Live:** https://mentortab.onrender.com/mentortab

Grounded in Kendall · Barkley · Greene · Dunn · Shafran · Deci-Ryan · Kagan.

## 📋 MentorTAB · Desk — for parents & staff
A registration concierge that answers the recurring questions — age, track, costs, schedule, carpools — from the group's own memory, with external info clearly marked.

**Live:** https://mentortab.onrender.com/desk

**One engine, any class:** each class is one file in `profiles/`, with its own isolated memory.
Hip-hop parents: https://mentortab.onrender.com/desk?class=hiphop

**In WhatsApp:** `whatsapp-bridge/` connects a class's parents group to Desk — see its README (Hebrew, step by step).
A group's messages are readable and writable **only by the bridge** (shared `BRIDGE_TOKEN`); the public web page answers from the class knowledge alone.

## Why the room is different
- **State before content** — kids arrive tired & hungry after school; behavior is often a state problem, not character.
- **~50% didn't choose to be here** — resistance is un-earned buy-in, not defiance (Self-Determination Theory).
- **~60% are introverts, on both sides** — low-social-load moves, never "talk it out in the group" (Kagan).

## Guardrails
A FIRST mentor is **not a therapist, not a babysitter, not a schoolteacher**. The engine never diagnoses, never stores a child's data, and routes real risk to a responsible adult.

## Architecture
- Coaching (web/mentortab.html) and Desk (web/desk.html)
- both served by server.py (FastAPI)
- powered by Claude + SQLite/FTS5
- shared: profiles/ · coach.py · talbot.py

## Run locally
    python tests/test_multiclass.py   # offline checks (needs: pip install httpx)
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-...
    uvicorn server:app --port 8000

© Bridge-iT Technologies · All rights reserved.

Individual*AI x Danya Dotan
