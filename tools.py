"""Tool implementations + dynamic schemas for the Talbot community group agent."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

from storage import (
    DEFAULT_GROUP,
    add_message as _add_message,
    find_senders_by_topic,
    get_messages_by_category,
    get_recent_messages,
    get_statistics as _get_statistics,
    search_messages as _search_messages,
)

if TYPE_CHECKING:
    from profile import Profile


MEMORY_TOOLS = {"add_message", "search_messages", "find_experts", "get_messages_by_category",
                "get_recent_messages", "get_statistics"}


def build_tool_schemas(profile: "Profile", memory: bool = True) -> list[dict]:
    """Tool schemas for a profile. Without memory, only the external web search is offered."""
    schemas = _all_tool_schemas(profile)
    return schemas if memory else [t for t in schemas if t["name"] not in MEMORY_TOOLS]


def _all_tool_schemas(profile: "Profile") -> list[dict]:
    cats = profile.category_keys
    members, group = profile.members_term, profile.group_term
    return [
        {"name": "add_message",
         "description": f"Store a new message from a {group} member in the community memory.",
         "input_schema": {"type": "object", "properties": {
             "sender_name": {"type": "string"}, "content": {"type": "string"},
             "category": {"type": "string", "enum": cats,
                          "description": "Options:\n" + "\n".join(f"  • {k}: {v}" for k, v in profile.categories.items())},
             "sender_phone": {"type": "string"}, "timestamp": {"type": "string"}},
             "required": ["sender_name", "content", "category"]}},
        {"name": "search_messages",
         "description": f"Full-text search across all stored {group} messages.",
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]}},
        {"name": "find_experts",
         "description": f"Find {members} who talked about a topic or need."
                        + (f" e.g. {', '.join(profile.focus_areas)}." if profile.focus_areas else ""),
         "input_schema": {"type": "object", "properties": {
             "topic": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["topic"]}},
        {"name": "get_messages_by_category",
         "description": f"Retrieve {group} messages filtered by category.",
         "input_schema": {"type": "object", "properties": {
             "category": {"type": "string", "enum": cats}, "limit": {"type": "integer", "default": 20}},
             "required": ["category"]}},
        {"name": "get_recent_messages",
         "description": f"Retrieve {group} messages from the last N days.",
         "input_schema": {"type": "object", "properties": {
             "days": {"type": "integer", "default": 7}, "limit": {"type": "integer", "default": 100}}, "required": []}},
        {"name": "get_statistics",
         "description": f"Return {group} activity statistics.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "web_search",
         "description": f"[EXTERNAL SOURCE] Search the web. Always state the result is external, not from {group}.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    ]


def add_message(sender_name, content, category="general", sender_phone=None, timestamp=None,
                group_id=DEFAULT_GROUP):
    return {"ok": True, "id": _add_message(sender_name=sender_name, content=content, category=category,
                                           sender_phone=sender_phone, timestamp=timestamp,
                                           group_id=group_id)}


def web_search(query: str) -> dict:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Talbot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        results = []
        if data.get("AbstractText"):
            results.append({"title": data.get("Heading", ""), "snippet": data["AbstractText"], "url": data.get("AbstractURL", "")})
        for rel in data.get("RelatedTopics", [])[:5]:
            if isinstance(rel, dict) and rel.get("Text"):
                results.append({"snippet": rel["Text"], "url": rel.get("FirstURL", "")})
        return {"source": "external_web", "results": results or [{"snippet": "No instant answer found.", "url": ""}]}
    except Exception as exc:
        return {"source": "external_web", "error": str(exc), "results": []}


_TOOL_MAP = {
    "add_message": lambda inp, g: add_message(**inp, group_id=g),
    "search_messages": lambda inp, g: _search_messages(**inp, group_id=g),
    "find_experts": lambda inp, g: find_senders_by_topic(**inp, group_id=g),
    "get_messages_by_category": lambda inp, g: get_messages_by_category(**inp, group_id=g),
    "get_recent_messages": lambda inp, g: get_recent_messages(**inp, group_id=g),
    "get_statistics": lambda inp, g: _get_statistics(group_id=g),
    "web_search": lambda inp, g: web_search(**inp),
}


def dispatch(tool_name: str, tool_input: dict[str, Any], group_id: str = DEFAULT_GROUP) -> Any:
    """Run a tool scoped to one group. Errors go back to the model, never crash the reply."""
    fn = _TOOL_MAP.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(dict(tool_input or {}), group_id)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
