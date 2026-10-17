"""Temp tool: re-record Bagian A — replay the recorded triggers with TODAY's prompt.

``reports/auto-reply-report.md`` scores the *answers* stored in
``sessions/current.json``, which were produced by the pre-fix prompt (2026-10-16).
That makes the report's headline count a measure of history, not of the current
code. This script closes that loop: it pairs each recorded result with the same
trigger the report uses (the merged run of fragments since the previous result,
falling back to the raw last fragment), rebuilds the conversation history the
reply actually saw, and runs the REAL worker on it — then writes a **new**
session-shaped file whose ``gemini_results`` are the fresh answers.

The original session is never modified. Point the report at the output:

    venv/bin/python _tmp_auto_reply_record.py
    venv/bin/python tools/auto_reply_report.py --recorded-only \
        --session reports/auto-reply-replay-session.json \
        --out reports/auto-reply-report-replay.md \
        --json reports/auto-reply-report-replay.json

A trigger the current pipeline intentionally skips (the F6 filler filter) spends
no AI call and produces no entry, so the replay can hold fewer results than the
source; the skipped triggers are listed in the file's ``replay`` block.
"""
import json
import os
import sys
import time
from datetime import datetime

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.abspath(__file__))
# The .env fallback path is read relative to the CWD, so pin it to the repo root.
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import src.gemini_worker as gw  # noqa: E402  (import after Qt app + sys.path)
from src.config import AI_BASE_URL, AI_MODEL, AI_PROVIDER  # noqa: E402

SOURCE = os.environ.get("AUTO_REPLY_RECORD_SOURCE", os.path.join("sessions", "current.json"))
OUT = os.environ.get(
    "AUTO_REPLY_RECORD_OUT", os.path.join("reports", "auto-reply-replay-session.json")
)
PURPOSE = "consultation"
HOST_ROLE = "consultant"


def read_file(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


HELPY = read_file("docs", "helpy.context.txt")
MAYA = read_file("maya.context.txt") or "Her name is Maya."
# The same context the live tier uses, so the replay is comparable to Bagian B.
CTX = {"host": HELPY or "HOSTCTX", "speaker": MAYA}

try:
    gw.get_ai_client()  # fail before spending anything, not mid-replay
except Exception as e:  # noqa: BLE001 - any config/build failure means "cannot record"
    print(f"SKIP: cannot build the provider client ({type(e).__name__}: {e})")
    sys.exit(0)

with open(SOURCE, encoding="utf-8") as f:
    session = json.load(f)

transcriptions = sorted(
    (t for t in (session.get("transcriptions") or []) if (t.get("text") or "").strip()),
    key=lambda t: t.get("timestamp", ""),
)
conversation = session.get("conversation") or []
results = session.get("gemini_results") or []

print(f"provider={AI_PROVIDER} model={AI_MODEL} base={AI_BASE_URL}")
print(f"source={SOURCE} ({len(results)} recorded answers, {len(conversation)} conversation turns)")
print()

new_results = []
entries = []
prev_ts = ""
for index, recorded in enumerate(results, 1):
    ts = recorded.get("timestamp", "")
    before = [t for t in transcriptions if t.get("timestamp", "") <= ts]
    last = before[-1] if before else None
    window = (
        [t for t in before
         if t.get("timestamp", "") > prev_ts and t.get("source") == last.get("source")]
        if last is not None else []
    )
    window_text = " ".join((t.get("text") or "").strip() for t in window).strip()
    last_text = (last.get("text") or "").strip() if last else ""
    trigger = window_text or last_text
    prev_ts = ts

    # History as it stood: the conversation prefix ending at the turn that
    # produced the trigger's last fragment (conversation text is verbatim).
    history = []
    if last is not None:
        for j, turn in enumerate(conversation):
            if turn.get("text") == last.get("text") and turn.get("role") == last.get("source"):
                history = conversation[: j + 1]

    outcome = {"text": "", "skipped": "", "error": ""}
    worker = gw.GeminiAutoReplyWorker(
        trigger, "English", conversation_history=list(history),
        include_pronunciation=False, purpose=PURPOSE, host_role=HOST_ROLE, context=CTX,
    )
    worker.result.connect(lambda t: outcome.__setitem__("text", t))
    worker.skipped.connect(lambda t: outcome.__setitem__("skipped", t))
    worker.error.connect(lambda t: outcome.__setitem__("error", t))
    t0 = time.monotonic()
    worker.run()
    latency_ms = round((time.monotonic() - t0) * 1000)

    status = "SKIPPED" if outcome["skipped"] else ("ERROR" if outcome["error"] else "reply")
    print(f"[A{index}] {status} ({latency_ms} ms) trigger={trigger[:70]!r}")
    if outcome["skipped"]:
        print(f"      skipped: {outcome['skipped']}  (no AI call — no entry written)")
    elif outcome["error"]:
        print(f"      error: {outcome['error']}")
    else:
        for line in outcome["text"].split("\n"):
            print("      | " + line)

    if outcome["text"] and not outcome["error"]:
        new_results.append({
            "mode": recorded.get("mode", "auto_reply"),
            "text": outcome["text"],
            # Keep the original timestamp so the report pairs the same trigger.
            "timestamp": ts,
        })
    entries.append({
        "case": f"A{index}",
        "trigger": trigger,
        "history_turns": len(history),
        "outcome": "skipped" if outcome["skipped"] else ("error" if outcome["error"] else "reply"),
        "skipped": outcome["skipped"],
        "error": outcome["error"],
        "latency_ms": latency_ms,
    })
    print()

replayed = dict(session)
replayed["gemini_results"] = new_results
replayed["replay"] = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "source": SOURCE,
    "source_id": session.get("id", ""),
    "provider": AI_PROVIDER,
    "model": AI_MODEL,
    "purpose": PURPOSE,
    "host_role": HOST_ROLE,
    "context": {"host": "docs/helpy.context.txt", "speaker": "maya.context.txt"},
    "triggers": len(results),
    "replied": len(new_results),
    "skipped": sum(1 for e in entries if e["outcome"] == "skipped"),
    "errors": sum(1 for e in entries if e["outcome"] == "error"),
    "entries": entries,
}

directory = os.path.dirname(os.path.abspath(OUT))
if directory:
    os.makedirs(directory, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(replayed, f, ensure_ascii=False, indent=2)

print(f"wrote {OUT}: {len(new_results)} new answer(s), "
      f"{replayed['replay']['skipped']} skipped, {replayed['replay']['errors']} error(s)")
print(f"source session untouched: {SOURCE}")
