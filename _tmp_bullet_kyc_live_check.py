"""Temp check (live): re-baseline the bullet-points KYC extraction with context.

Adding the Host/Speaker **reference context** to `BulletPointsWorker` changes the
one prompt whose output is a *finding* the user reads: the extracted Speaker
profile. The risk is leakage — the pre-identified profile (or the Host's product
facts) coming back out as if the speaker had said it.

This runs the REAL worker (real provider, real `SYSTEM_INSTRUCTION`) twice on the
same synthetic conversation:

  * **baseline** — no context at all (the pre-feature prompt);
  * **with context** — a "trap" context that names a speaker identity the
    conversation never mentions.

and asserts that

  1. the trap facts (name / occupation / location / host product) never appear in
     the extracted profile or the bullet list, and
  2. the pain points the speaker really stated are still captured — i.e. the block
     did not degrade extraction.

Opt-in (it spends real tokens): gate with `BULLET_KYC_LIVE_TESTS=1`. Exits 0 with
a notice when the flag is unset or the provider cannot be built.

    BULLET_KYC_LIVE_TESTS=1 venv/bin/python _tmp_bullet_kyc_live_check.py
    BULLET_KYC_LIVE_TESTS=1 venv/bin/python _tmp_bullet_kyc_live_check.py --repeat 2
"""

import argparse
import json
import os
import re
import sys
import time

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import src.bullet_points_worker as bpw  # noqa: E402

# A conversation that says a lot about pain/goals and NOTHING about who the
# speaker is — so any identity in the output can only have come from the context.
TRANSCRIPT = [
    ("host", "So how does your team run discovery calls today?"),
    ("speaker", "We record them and someone writes notes afterwards. It takes hours."),
    ("speaker", "The notes are inconsistent, and we lose the details that matter for the proposal."),
    ("host", "What would better look like?"),
    ("speaker", "I want the key points captured automatically. And it has to work in German too."),
    ("speaker", "Budget is approved for this quarter, but my team is small."),
]

# The trap: identity details only in the *context*, never in the conversation.
TRAP_CONTEXT = {
    "host": "Host (us): we sell Helpy, a consulting copilot that turns calls into briefs.",
    "speaker": "Speaker: Zorblax Quintenhall, CTO of Northwind Turbines, based in Reykjavik.",
}

# Distinctive tokens that appear ONLY in the context.
TRAP_TOKENS = ["Zorblax", "Quintenhall", "Northwind", "Turbines", "Reykjavik", "CTO"]
# Tokens that appear only in the Host's product facts (also must not leak).
HOST_TOKENS = ["Helpy", "copilot"]
# Something the speaker actually said (a pain point), for the "no degradation" half.
SPOKEN_TOKENS = ["hours", "inconsistent", "notes", "german", "budget", "small"]

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait_for(predicate, timeout_ms=120000):
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def run_worker(context=None, rebuild=True):
    """Run the real worker once; return (result dict or None, error or None, seconds)."""
    worker = bpw.BulletPointsWorker([], {}, TRANSCRIPT, rebuild=rebuild, context=context)
    out = {}
    started = time.time()
    worker.result.connect(lambda payload: out.setdefault("result", payload))
    worker.error.connect(lambda msg: out.setdefault("error", msg))
    worker.start()
    wait_for(lambda: "result" in out or "error" in out)
    worker.wait(5000)
    return out.get("result"), out.get("error"), time.time() - started


def blob(profile, items):
    """Everything the model produced, lowercased, for a leakage scan."""
    return (json.dumps(profile, ensure_ascii=False) + "\n" + "\n".join(items or [])).lower()


def scan(tokens, text):
    return [t for t in tokens if re.search(r"\b" + re.escape(t.lower()), text)]


def verbatim_runs(context, text, n=6):
    """Runs of >= n consecutive words from the context that appear verbatim in `text`.

    A blunt copy detector: the profile is supposed to be *extracted*, so a long
    verbatim overlap with a background block is a leak dressed as a finding.
    """
    def words(value):
        return re.findall(r"[a-z0-9']+", (value or "").lower())

    hay = words(text)
    hay_set = set()
    for i in range(len(hay) - n + 1):
        hay_set.add(" ".join(hay[i:i + n]))
    hits = []
    for role in ("host", "speaker"):
        src = words(context.get(role))
        for i in range(len(src) - n + 1):
            phrase = " ".join(src[i:i + n])
            if phrase in hay_set:
                hits.append(phrase)
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="repeat the with-context run N times")
    args = parser.parse_args()

    if os.environ.get("BULLET_KYC_LIVE_TESTS") != "1":
        print("SKIP: set BULLET_KYC_LIVE_TESTS=1 to spend real tokens")
        return 0
    try:
        bpw.get_ai_client()
    except Exception as exc:  # missing key / bad provider
        print(f"SKIP: provider unavailable ({exc})")
        return 0

    print("=" * 72)
    print("baseline (no context)")
    print("=" * 72)
    base_profile, base_error, base_secs = run_worker(context=None)
    if base_error:
        check("baseline worker succeeded", False, str(base_error))
        return 1
    base_items = (base_profile or {}).get("items") or []
    base_speaker = (base_profile or {}).get("speaker") or {}
    print(json.dumps({"bullets": base_items, "speaker": base_speaker}, ensure_ascii=False, indent=2))
    print(f"({base_secs:.1f}s)")
    check("baseline returned a profile", bool(base_speaker), str(base_speaker))
    base_text = blob(base_speaker, base_items)
    check("baseline captured spoken pain points",
          bool(scan(SPOKEN_TOKENS, base_text)), str(scan(SPOKEN_TOKENS, base_text)))

    for attempt in range(1, args.repeat + 1):
        print("\n" + "=" * 72)
        print(f"with trap context (run {attempt}/{args.repeat})")
        print("=" * 72)
        # The real Host file (when present) rides along with the identity trap, so
        # the run exercises the user's own context too.
        context = dict(TRAP_CONTEXT)
        real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "helpy.context.txt")
        if os.path.isfile(real):
            with open(real, encoding="utf-8", errors="replace") as handle:
                context["host"] = handle.read()
        profile, error, secs = run_worker(context=context, rebuild=True)
        if error:
            check(f"run {attempt} succeeded", False, str(error))
            continue
        items = (profile or {}).get("items") or []
        speaker = (profile or {}).get("speaker") or {}
        print(json.dumps({"bullets": items, "speaker": speaker}, ensure_ascii=False, indent=2))
        print(f"({secs:.1f}s)")
        text = blob(speaker, items)

        leaked = scan(TRAP_TOKENS, text)
        check(f"run {attempt}: no speaker-identity leakage", not leaked, str(leaked))
        host_leaked = scan(HOST_TOKENS, text)
        check(f"run {attempt}: no host-product leakage", not host_leaked, str(host_leaked))
        copied = verbatim_runs(context, text)
        check(f"run {attempt}: no verbatim block copied into a finding", not copied, str(copied[:2]))
        check(f"run {attempt}: still captured spoken pain points",
              bool(scan(SPOKEN_TOKENS, text)), str(scan(SPOKEN_TOKENS, text)))
        check(f"run {attempt}: the profile kept its shape",
              isinstance(speaker, dict) and "name" in speaker, str(sorted(speaker))[:90])

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
