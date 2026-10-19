#!/usr/bin/env python3
"""Talbot — personalized community group agent (the MentorTAB · Desk engine)."""

from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic

from profile import Profile, list_profiles
from storage import DEFAULT_GROUP, init_db
from tools import build_tool_schemas, dispatch

MODEL = os.environ.get("TALBOT_MODEL", "claude-opus-4-7")


def build_system_prompt(profile: Profile) -> str:
    lines = [profile.system_prompt, "", f"## About {profile.name}", profile.about, "",
             f"## Message categories for {profile.group_term}"]
    for key, desc in profile.categories.items():
        lines.append(f"  • **{key}**: {desc}")
    if profile.key_people:
        lines += ["", "## Key people"] + [f"  • {p['name']} — {p['role']}" for p in profile.key_people]
    if profile.focus_areas:
        lines += ["", "## Focus areas to track", "  " + ", ".join(profile.focus_areas)]
    if profile.custom_instructions:
        lines += ["", "## Specific instructions"] + [f"  • {i}" for i in profile.custom_instructions]
    lines += ["", "## Core rules",
              "  • Internal group knowledge takes priority over external sources.",
              f"  • When you use web_search, label it: '⚠️ מקור חיצוני (אינטרנט), לא ממידע {profile.group_term}.'",
              "  • Never expose private info, secrets, or personal details beyond what members shared publicly.",
              "  • Never fabricate statements in a member's name.",
              "  • Never invent members, families or past messages. Only mention people or messages that your "
              "memory tools actually returned; if memory is empty, say so plainly.",
              "  • Match the language of the user's message (Hebrew / English).",
              "  • Replies are shown as plain text, often inside WhatsApp: keep them short (up to ~8 lines), "
              "no markdown headings (#) or tables, no **double asterisks**; use simple bullets (•) and at most "
              "an occasional *single-asterisk* emphasis."]
    return "\n".join(lines)


class TalbotAgent:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        init_db()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.tool_schemas = build_tool_schemas(profile)
        self.system_prompt = build_system_prompt(profile)
        self.group_id = profile.key or DEFAULT_GROUP
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})
        while True:
            resp = self.client.messages.create(model=MODEL, max_tokens=4096, system=self.system_prompt,
                                                tools=self.tool_schemas, messages=self.history)
            self.history.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "end_turn":
                return "\n".join(b.text for b in resp.content if hasattr(b, "text"))
            if resp.stop_reason == "tool_use":
                results = [{"type": "tool_result", "tool_use_id": b.id,
                            "content": json.dumps(dispatch(b.name, b.input, self.group_id),
                                                  ensure_ascii=False, default=str)}
                           for b in resp.content if b.type == "tool_use"]
                self.history.append({"role": "user", "content": results})
                continue
            break
        return "[No response]"

    def run_interactive(self) -> None:
        print(f"Talbot ready — profile: {self.profile.name}\nType 'exit' to quit.\n")
        while True:
            try:
                ui = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!"); break
            if not ui:
                continue
            if ui.lower() in {"exit", "quit", "bye"}:
                print("Goodbye!"); break
            print(f"\nTalbot: {self.chat(ui)}\n")


def seed_demo(profile: Profile) -> None:
    from storage import add_message
    if not profile.demo_messages:
        print(f"No demo messages in '{profile.name}'."); return
    print(f"Seeding {len(profile.demo_messages)} demo messages...")
    for m in profile.demo_messages:
        add_message(sender_name=m["sender_name"], content=m["content"], category=m["category"],
                    sender_phone=m.get("sender_phone"), timestamp=m.get("timestamp"),
                    group_id=profile.key or DEFAULT_GROUP)
    print("Done.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Talbot community agent")
    ap.add_argument("--profile", "-p", default="first_robotics")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--seed-demo", action="store_true")
    ap.add_argument("--query", "-q")
    args = ap.parse_args()
    if args.list_profiles:
        print("Available profiles:"); [print(f"  • {p}") for p in list_profiles()]; return
    profile = Profile.load_by_name(args.profile)
    init_db()
    if args.seed_demo:
        seed_demo(profile)
    try:
        agent = TalbotAgent(profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr); sys.exit(1)
    print(agent.chat(args.query)) if args.query else agent.run_interactive()


if __name__ == "__main__":
    main()
