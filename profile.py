"""Profile loader — defines per-deployment personality and domain config."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROFILES_DIR = Path(__file__).parent / "profiles"
DEFAULT_PROFILE = "first_robotics"


@dataclass
class Profile:
    name: str
    type: str
    language: str
    categories: dict[str, str]
    system_prompt: str
    about: str = ""
    terminology: dict[str, str] = field(default_factory=dict)
    focus_areas: list[str] = field(default_factory=list)
    key_people: list[dict[str, str]] = field(default_factory=list)
    custom_instructions: list[str] = field(default_factory=list)
    demo_messages: list[dict[str, Any]] = field(default_factory=list)
    display_name: str = ""          # short label for UIs, e.g. "היפ-הופ"
    suggested_questions: list[str] = field(default_factory=list)  # quick-ask chips on the Desk page
    key: str = ""                   # file stem; also the memory scope (group_id)

    @property
    def category_keys(self) -> list[str]:
        return list(self.categories.keys())

    @property
    def members_term(self) -> str:
        return self.terminology.get("members", "members")

    @property
    def group_term(self) -> str:
        return self.terminology.get("group", "group")

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def load_by_name(cls, name: str) -> "Profile":
        path = PROFILES_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile '{name}' not found. Available: {list_profiles()}")
        profile = cls.load(path)
        profile.key = name
        return profile


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))
