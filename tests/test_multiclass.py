"""Regression checks for multi-class Desk, group-memory access, and history trimming.

Runs fully offline with a stubbed Claude and a temporary database:

    pip install -r requirements.txt httpx
    python tests/test_multiclass.py
"""

import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ.pop("BRIDGE_TOKEN", None)

import storage  # noqa: E402

storage.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"  # never touch a real talbot.db

import server  # noqa: E402
import talbot  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from profile import Profile  # noqa: E402

TOKEN = "test-bridge-token"
BRIDGE = {"X-Bridge-Token": TOKEN}

# ---- stub Claude: first asks to search memory (if it can), then answers ----
calls = []


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeMessages:
    def create(self, **kw):
        calls.append(kw)
        tool_names = {t["name"] for t in kw["tools"]}
        already_used_tool = any(m["role"] == "user" and isinstance(m["content"], list) for m in kw["messages"])
        if "search_messages" in tool_names and not already_used_tool:
            return types.SimpleNamespace(stop_reason="tool_use", content=[
                Block(type="tool_use", id="t1", name="search_messages", input={"query": 'הסעה "רמת-גן"'})])
        return types.SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="תשובה")])


class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()


talbot.anthropic.Anthropic = FakeAnthropic
client = TestClient(server.app)
failures = 0


def check(cond, msg):
    global failures
    print(("✓ " if cond else "✗ FAIL ") + msg)
    failures += 0 if cond else 1


def tool_results(call):
    return [json.loads(m["content"][0]["content"]) for m in call["messages"]
            if m["role"] == "user" and isinstance(m["content"], list)]


# ---- profiles & routes ----
hp = Profile.load_by_name("hiphop")
check(hp.key == "hiphop" and hp.display_name == "היפ-הופ" and hp.suggested_questions, "hiphop profile loads")
check("hiphop" in client.get("/health").json()["classes"], "/health lists classes")
check("active" in client.get("/profiles").json(), "/profiles keeps 'active' for old callers")
check(client.get("/profile-info", params={"class": "hiphop"}).json()["display_name"] == "היפ-הופ", "/profile-info?class=hiphop")
check(client.get("/profile-info", params={"class": "nope"}).status_code == 404, "unknown class -> 404")
for path in ["/", "/mentortab", "/desk", "/widget"]:
    check(client.get(path).status_code == 200, f"GET {path}")

# ---- group memory is bridge-only ----
msg = {"sender_name": "נועה", "content": "מחפשת הסעה מרמת גן לחוג", "profile": "hiphop"}
check(client.post("/ingest", json=msg).status_code == 503, "ingest refused while BRIDGE_TOKEN is unset")
os.environ["BRIDGE_TOKEN"] = TOKEN
check(client.post("/ingest", json=msg).status_code == 401, "ingest without token -> 401")
check(client.post("/ingest", json=msg, headers={"X-Bridge-Token": "wrong"}).status_code == 401, "ingest with wrong token -> 401")
check(client.post("/ingest", json=msg, headers=BRIDGE).json()["class"] == "hiphop", "ingest with token stores to hiphop")
client.post("/ingest", json={"sender_name": "דנה", "content": "מחפשת הסעה מחיפה"}, headers=BRIDGE)

# ---- memory isolation between classes ----
check([m["sender_name"] for m in storage.search_messages("הסעה", group_id="hiphop")] == ["נועה"], "search isolated: hiphop")
check([m["sender_name"] for m in storage.search_messages("הסעה", group_id="first_robotics")] == ["דנה"], "search isolated: robotics")
for q in ['רמת-גן "בדיוק"', "a:b OR", '""', "-*^"]:
    storage.search_messages(q, group_id="hiphop")
check(True, "search tolerates quotes / hyphens / operators")

# ---- chat: bridge gets memory, public web does not ----
check(client.post("/chat", json={"message": "x", "profile": "hiphop"}, headers={"X-Bridge-Token": "wrong"}).status_code == 401,
      "bridge chat with wrong token -> 401 (fails loudly)")
calls.clear()
r = client.post("/chat", json={"message": "יש הסעות?", "session_id": "wa-1", "profile": "hiphop"}, headers=BRIDGE)
check(r.status_code == 200, "bridge /chat ok")
results = tool_results(calls[-1])
check(results and results[0][0]["sender_name"] == "נועה", "bridge chat searched hiphop memory only")

calls.clear()
r = client.post("/chat", json={"message": "מה כתבו ההורים?", "session_id": "web-1", "profile": "hiphop"})
check(r.status_code == 200, "public /chat ok")
check({t["name"] for t in calls[-1]["tools"]} == {"web_search"}, "public chat has no memory tools")
check("NO access to the group's messages" in calls[-1]["system"], "public chat is told it has no group memory")
check(not tool_results(calls[-1]), "public chat read nothing from memory")

agent = talbot.TalbotAgent(hp, memory=False)
check("error" in agent._run_tool("search_messages", {"query": "הסעה"}), "memory tool refused even if called directly")

os.environ["BRIDGE_TOKEN"] = "סיסמה-בעברית"
check(server.bridge_authorized("סיסמה-בעברית") and not server.bridge_authorized("אחרת"), "non-ASCII (Hebrew) password works")
os.environ["BRIDGE_TOKEN"] = TOKEN

# ---- legacy rows from before multi-class are adopted by the default class ----
storage.add_message("ותיק", "הודעה ישנה", group_id=storage.DEFAULT_GROUP)
moved = storage.adopt_legacy_rows("first_robotics")
check(moved == 1 and storage.search_messages("ישנה", group_id="first_robotics"), "legacy 'default' rows adopted")

# ---- trimming never starts on an orphaned tool_result ----
hist = [{"role": "user", "content": "q"}]
for _ in range(30):
    hist += [{"role": "assistant", "content": [{"type": "tool_use"}]},
             {"role": "user", "content": [{"type": "tool_result"}]}]
hist.append({"role": "user", "content": "last"})
t = server.trim_history(hist)
check(len(t) <= server.MAX_HISTORY_MESSAGES and server._is_plain_user_turn(t[0]), "trim_history starts on a user turn")

print("\nALL PASSED" if not failures else f"\n{failures} FAILED")
sys.exit(1 if failures else 0)
