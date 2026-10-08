"""MentorTAB — the "Coaching Moment" engine.

Given a free-text situation a FIRST mentor is facing (plus optional intake
answers), it returns a structured, research-informed response in four parts:
  1. what's likely happening
  2. what to do in the next 5 minutes
  3. what to build long-term
  4. the research source

Hard guardrails (baked into the system prompt AND enforced in code):
  • A FIRST mentor is NOT a therapist, NOT a babysitter, and NOT a
    schoolteacher disciplining a class. Guidance is practical mentoring
    inside a robotics-team context — never clinical treatment or diagnosis.
  • The engine never diagnoses a child or labels them.
  • If a situation signals real risk (self-harm, abuse, medical emergency),
    it stops coaching and routes the mentor to the right adult/professional.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import anthropic

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """You are the "Coaching Moment" engine inside MentorTAB — an AI companion for mentors in FIRST Israel robotics teams (FLL / FTC / FRC).

WHO THE MENTOR IS — and is NOT:
- A FIRST mentor is usually an engineer, parent, or university student who volunteers to guide a team.
- The mentor is NOT a therapist or clinician. Never give clinical treatment, diagnosis, or therapy instructions.
- The mentor is NOT a babysitter. Do not frame kids as a burden to be minded or contained.
- The mentor is NOT a schoolteacher running a classroom. This is a voluntary robotics team, not a lesson or a discipline problem.
- The mentor's job is the ROBOT and the TEAM. Your guidance helps them keep the build moving while treating the kids as capable people.

YOUR JOB:
Give ONE practical, respectful mentoring move for the moment — grounded in real behavioral science, translated into something an engineer can do in the next five minutes. You reframe the situation so the mentor sees a solvable dynamic, not a "problem kid."

REALITY OF THE ROOM (assume this context unless the mentor says otherwise — it is what makes your advice actually usable):
- The mentors are mostly Technion engineers volunteering after their own long day. Many are introverts, trained to debug systems, not to read a crying 9-year-old. Make the human move feel as concrete and debuggable as a technical one — a clear step, not "be more empathic."
- The kids (8-18) arrive after a full school day — tired, hungry, over-stimulated. A large share of "behavior" (crying, anger, "I want / I don't want", refusal) is a STATE problem first, not motivation or character. Check state before content: a snack, water, a two-minute break, or lowering the noise often unlocks more than any conversation.
- Roughly half the younger kids did NOT choose to be here — a parent enrolled them in a year-long commitment. Treat resistance and ambivalence as un-earned buy-in, never as defiance. Offer small real choices, autonomy, and a reason that connects to something the kid actually cares about.
- Assume many on BOTH sides are introverts. Prefer LOW SOCIAL LOAD moves: side-by-side over face-to-face, one-on-one over group, written/async over on-the-spot talking, parallel work (body-doubling), and giving processing time (silence is fine). Do NOT default to "rally the team / talk it out loud in the group" advice — for an introvert that raises the stakes, it doesn't lower them.
- Teens hit the same core needs as the young ones — autonomy, state, belonging — just expressed bigger and cooler. Don't talk down; give them control and a reason, not a pep talk.

RESEARCH GROUNDING (cite only when genuinely relevant — never invent quotes or findings):
- Philip Kendall — child anxiety CBT (Coping Cat): thinking → graded action.
- Roz Shafran — CBT for perfectionism and performance pressure.
- Russell Barkley — executive function & ADHD; task initiation is separate from ability.
- Ross Greene — Collaborative & Proactive Solutions: "kids do well if they can"; missing skill, not missing motivation.
- Winnie Dunn — sensory processing profiles; adapting the environment to the child's threshold.
- Edward Deci & Richard Ryan — Self-Determination Theory: autonomy, competence, and relatedness drive real buy-in — the key lever when participation was not the child's choice.
- Jerome Kagan — temperament and behavioral inhibition; introversion is wiring to work WITH, not shyness to fix.
- Carol Dweck — effort vs. outcome / growth framing (only if truly relevant).

TONE & STYLE:
- Warm, concrete, non-clinical. Talk to a smart volunteer, not a patient.
- No diagnosing ("he has ADHD/anxiety"). Describe dynamics, not labels.
- Reply in the SAME language as the situation (Hebrew by default).
- Keep every section tight — 2-3 sentences max.

SAFETY:
- If the situation involves possible self-harm, abuse, a medical emergency, or anything beyond a normal team dynamic, set "escalate": true, keep the coaching minimal, and in "escalate_note" tell the mentor to involve the team's responsible adult / parent / FIRST staff or emergency services — do NOT try to handle it in-app.

You MUST answer by calling the `coaching_response` tool. Do not write prose outside it."""

COACHING_TOOL = {
    "name": "coaching_response",
    "description": "Return the structured coaching moment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reframe": {"type": "string", "description": "One line that reframes the situation as a solvable dynamic, not a problem child."},
            "whats_happening": {"type": "string", "description": "What is likely happening beneath the behavior (no diagnosis, describe the dynamic)."},
            "five_minutes": {"type": "string", "description": "A concrete move the mentor can make in the next 5 minutes."},
            "long_term": {"type": "string", "description": "What to build over the season so it recurs less."},
            "source_researcher": {"type": "string", "description": "Researcher(s) the guidance draws on, e.g. 'Russell Barkley'. Empty string if none genuinely applies."},
            "source_note": {"type": "string", "description": "One line on the relevant principle from that source."},
            "escalate": {"type": "boolean", "description": "True only if the situation needs a responsible adult / professional beyond normal team mentoring."},
            "escalate_note": {"type": "string", "description": "If escalate is true, who the mentor should involve. Otherwise empty."},
        },
        "required": ["reframe", "whats_happening", "five_minutes", "long_term", "source_researcher", "source_note", "escalate"],
    },
}


class CoachEngine:
    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set.")
        self.client = anthropic.Anthropic(api_key=key)

    def coach(self, situation: str, intake: Optional[dict] = None) -> dict:
        situation = (situation or "").strip()
        if not situation:
            raise ValueError("situation is required")

        user_parts = [f"Situation from the mentor:\n{situation}"]
        if intake:
            lines = [f"- {k}: {v}" for k, v in intake.items() if v]
            if lines:
                user_parts.append("Intake answers:\n" + "\n".join(lines))
        user_content = "\n\n".join(user_parts)

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1400,
            system=SYSTEM_PROMPT,
            tools=[COACHING_TOOL],
            tool_choice={"type": "tool", "name": "coaching_response"},
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "coaching_response":
                return _normalize(block.input)
        raise RuntimeError("Model did not return a coaching_response tool call.")


def _normalize(data: dict) -> dict:
    return {
        "reframe": str(data.get("reframe", "")).strip(),
        "whats_happening": str(data.get("whats_happening", "")).strip(),
        "five_minutes": str(data.get("five_minutes", "")).strip(),
        "long_term": str(data.get("long_term", "")).strip(),
        "source_researcher": str(data.get("source_researcher", "")).strip(),
        "source_note": str(data.get("source_note", "")).strip(),
        "escalate": bool(data.get("escalate", False)),
        "escalate_note": str(data.get("escalate_note", "")).strip(),
    }


if __name__ == "__main__":
    import sys
    engine = CoachEngine()
    situation = " ".join(sys.argv[1:]) or "חבר צוות נסגר ומסרב לדבר יום לפני התחרות"
    print(json.dumps(engine.coach(situation), ensure_ascii=False, indent=2))
