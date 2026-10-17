#!/usr/bin/env python
"""Report generator for the auto-reply (AI suggestion) pipeline.

Answers, per case: what was asked, what the AI answered, and why that answer is
right or wrong — as a readable Markdown report plus a JSON sidecar.

Two sources, both in the same report:

  * **Bagian A — replay sesi terekam.** Every ``aireply_results`` entry in
    ``sessions/current.json`` is paired with the utterance that triggered it
    (the merged run of fragments of the same source since the previous result,
    plus the raw last fragment). Free: no model is ever called.
  * **Bagian B — skenario live.** The same scenarios as
    ``_tmp_auto_reply_live_check.py`` (L1, L2, L3, L4, L5, L7, L10) run against
    the provider configured in ``.env``. Gated by ``AUTO_REPLY_LIVE_TESTS=1``,
    so a run without credentials (or without the flag) costs nothing.

The analysis is deterministic — the same keyword/regex contracts the test suite
already uses (product terms, invented-feature terms, question-back, bare ack,
client-voice, filler triggers) — so a verdict is reproducible and diffable. It
never judges style, only the contracts we can assert.

    venv/bin/python tools/auto_reply_report.py                    # Bagian A saja
    AUTO_REPLY_LIVE_TESTS=1 venv/bin/python tools/auto_reply_report.py
    venv/bin/python tools/auto_reply_report.py --repeat 3 --out reports/x.md

Exit code is 0 unless the report itself could not be written: this is an
evidence tool, not a gate (the gate is the test suite).
"""

import argparse
import copy
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The .env fallback path is read relative to the CWD, so pin it to the repo root.
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import src.gemini_worker as gw  # noqa: E402  (import after Qt app + sys.path)
from src.config import (  # noqa: E402
    AI_BASE_URL,
    AI_MODEL,
    AI_PROVIDER,
    DISABLE_MODEL_REASONING,
    PURPOSES_PATH,
)
from src.decision_client import DecisionClient  # noqa: E402
from src.purposes import BUILTIN_PURPOSES  # noqa: E402

SESSION_PATH = os.path.join(REPO, "sessions", "current.json")
DEFAULT_OUT = os.path.join(REPO, "reports", "auto-reply-report.md")
DEFAULT_JSON = os.path.join(REPO, "reports", "auto-reply-report.json")

PURPOSE = "consultation"
HOST_ROLE = "consultant"

# The role the live worker is built with. ``smart`` is the app's default for
# "I am:" and is the only mode in which JEV is asked ``host_role`` at all
# (``build_questions`` only adds it when ``smart_role`` is true), so a JEV run
# that wants to measure role adoption has to use it.
ROLES = ("consultant", "client", "smart")

# --- detectors -----------------------------------------------------------
# Mirrors _tmp_auto_reply_live_check.py:86-93 and :229. The constants are copied
# rather than imported because that file runs its whole suite at import time.
PRODUCT_TERMS = ["helpy", "brief", "gap", "gaps", "summary", "notes", "note",
                 "capture", "roadmap", "transcript", "both sides"]

# Generic SaaS words the model should NOT reach for when no Host profile is
# attached: their presence is a hallucinated product, not a grounded one.
INVENTION_TERMS = ["dashboard", "integrations", "integration", "platform", "api",
                   "subscription", "onboarding", "sign up", "account", "accounts",
                   "crm", "pipeline"]

# Ambiguous invention words: only a hallucination when the sentence does NOT also
# name a real product mechanism ("Helpy's consulting pipeline" is a metaphor, not
# an invented feature — the documented false positive).
AMBIGUOUS_INVENTION_TERMS = {"api", "crm", "platform", "pipeline"}

# Invented-capability claims that the word list alone missed. The strong ones are
# never legitimate in a grounded answer; the weak ones (a product that "syncs" or
# acts "automatically") are fine in a sentence that already names the product.
STRONG_INVENTION_PATTERNS = [
    (re.compile(r"\bfree trial\b", re.I), "free trial"),
    (re.compile(r"\bweekly report\b", re.I), "weekly report"),
    (re.compile(r"\byou get a\b[^.!?\n]{0,40}\breport\b", re.I), "you get a … report"),
]
WEAK_INVENTION_PATTERNS = [
    (re.compile(r"\bsyncs?\b", re.I), "syncs"),
    (re.compile(r"\bautomatic(?:ally)?\b", re.I), "automatically"),
]

CLIENT_VOICE_RE = re.compile(r"\bmy (concrete )?need\b|\bwhat I(?:'d| would) need\b", re.I)
ACK_RE = re.compile(r"^(thanks|thank you|great question|certainly|sure)\b", re.I)
HEADER_RE = re.compile(r"^(\w+) Text:\s*(.*)$")

# Local fallback for the filler test. Fase 2 adds ``src/filler_filter.py``, which
# this prefers when it exists — so the report and the product agree on what a
# filler is.
_LOCAL_FILLERS = {
    "okay", "ok", "mm-hm", "mm", "uh-huh", "yeah", "yes", "yep", "right", "sure",
    "exactly", "you nailed it", "got it", "i see", "hmm", "alright", "thanks",
    "thank you", "great", "nice", "cool", "interesting",
}


def _normalize_utterance(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9' -]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _is_filler_segment(segment: str) -> bool:
    norm = _normalize_utterance(segment)
    if not norm:
        return False
    return norm in _LOCAL_FILLERS or re.sub(r"(.)\1{2,}", r"\1", norm) in _LOCAL_FILLERS


def is_filler(text: str) -> bool:
    """True when an utterance is a pure acknowledgment/filler.

    A *run* of acknowledgments ("Exactly. You nailed it.") is still a filler: the
    recorded session shows such a run triggering a full reply, so checking only
    the whole string would miss it.
    """
    try:
        from src.filler_filter import is_filler as impl  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - the module is optional until Fase 2 lands
        impl = None
    if impl is not None:
        return bool(impl(text))
    segments = [s for s in re.split(r"[.!?,;:\n]+", (text or "").lower()) if s.strip()]
    if not segments:
        return False
    return all(_is_filler_segment(s) for s in segments)


# Maps a finding to the ranked cause it belongs to (see the flow review), so the
# report ties each symptom back to the structural reason.
FINDING_CAUSE = {
    "no_reply": "cause 7 / F7 (trigger ditolak) atau error provider",
    "skipped": "bukan cacat (filter filler F6 atau JEV sengaja diam)",
    "question_back": "cause 3 / F2 (objective tidak menyuruh menjawab dulu)",
    "bare_ack": "cause 3 / F2",
    "thin": "cause 3 / F2",
    "ungrounded": "cause 1 / F1 (tidak ada grounding rule)",
    "grounding_late": "cause 1 / F1 (grounding melemah, rekomendasi tidak menyebut produk)",
    "unexpected_product_claim": "cause 1 / F1 (mengarang produk saat tidak ada Host profile)",
    "invented": "cause 1 / F1",
    "role_inversion": "cause 4 / data fix (maya.context.txt vs profil speaker)",
    "no_preamble": "kontrak format (bukan bug perilaku)",
    "language": "kontrak format (bukan bug perilaku)",
    "filler_trigger": "cause 6 / F6 (tidak ada filter filler)",
    "amnesia": "cause 5 (prior suggestions tidak di-feed back)",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# --- helpers -------------------------------------------------------------
def read_file(*parts) -> str:
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_session(path=None) -> dict:
    """Read the session Bagian A replays (``--session``, default ``sessions/current.json``).

    Overriding the path lets the report score a *replayed* record (the same
    triggers answered by the current prompt) the same way it scores the live one.
    """
    try:
        with open(path or SESSION_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def body_of(reply: str) -> str:
    """Drop the 'Speaker's move:' preamble and unwrap any '<Language> Text:' header.

    The model writes the reply on the SAME line as the header
    (``English Text: <reply>``), so the header is unwrapped, not dropped.
    """
    keep = []
    for line in (reply or "").split("\n"):
        s = line.strip()
        if s.startswith("Speaker's move:"):
            continue
        m = HEADER_RE.match(s)
        if m:
            keep.append(m.group(2))
            continue
        keep.append(line)
    return "\n".join(keep).strip()


def preamble_of(reply: str) -> str:
    for line in (reply or "").split("\n"):
        if line.strip().startswith("Speaker's move:"):
            return line.strip()
    return ""


def header_language(reply: str) -> str:
    m = re.search(r"^(\w+) Text:", reply or "", re.M)
    return m.group(1) if m else ""


def first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)
    return parts[0] if parts else (text or "").strip()


def mentions(text: str, words) -> list:
    return sorted({w for w in words if re.search(rf"\b{re.escape(w)}\b", text or "", re.I)})


def sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def invented_signals(text: str) -> list:
    """Invention terms/claims, with the documented false positives removed.

    A sentence that already names a real product mechanism is grounded, so an
    ambiguous word there ("Helpy's consulting pipeline") or a weak capability
    phrase ("Helpy automatically captures both sides") is not an invention.
    Unambiguous SaaS nouns and strong capability claims still are.
    """
    signals = set()
    for sentence in sentences(text):
        grounded = bool(mentions(sentence, PRODUCT_TERMS))
        for term in mentions(sentence, INVENTION_TERMS):
            if grounded and term in AMBIGUOUS_INVENTION_TERMS:
                continue
            signals.add(term)
        strong = [label for pattern, label in STRONG_INVENTION_PATTERNS
                  if pattern.search(sentence)]
        # "weekly report" and "you get a … report" describe the same claim.
        if "weekly report" in strong:
            strong = [label for label in strong if label != "you get a … report"]
        signals.update(strong)
        if not grounded:
            for pattern, label in WEAK_INVENTION_PATTERNS:
                if pattern.search(sentence):
                    signals.add(label)
    return sorted(signals)


def one_line(text: str, limit: int = 120) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


# --- analysis ------------------------------------------------------------
def analyze(answer: str, trigger: str, *, expect_language=None, latency_ms=None,
            expect_grounded: bool = True, skipped: str = "") -> dict:
    """Deterministic verdict + reasons for one answer.

    ``expect_grounded`` is False for the cases that deliberately run without a
    Host profile (L5/L7), where naming the product would itself be a defect.
    ``skipped`` means no reply was produced *by design* (the filler filter or
    JEV), so the empty answer is reported as such instead of as a defect.
    """
    answer = answer or ""
    body = body_of(answer)
    first = first_sentence(body)
    grounded = mentions(body, PRODUCT_TERMS)
    grounded_first = mentions(first, PRODUCT_TERMS)
    findings = []
    if skipped:
        findings.append(("skipped", "low",
                         f"Tidak ada jawaban: {skipped} — perilaku yang diinginkan, bukan cacat."))
    elif not body:
        findings.append(("no_reply", "high", "Tidak ada jawaban yang dihasilkan."))
    else:
        if first.endswith("?"):
            findings.append(("question_back", "medium", f"Kalimat pertama pertanyaan balik: {first!r}"))
        if ACK_RE.match(body):
            findings.append(("bare_ack", "medium", f"Dibuka dengan acknowledgment: {first!r}"))
        if len(body.split()) < 10:
            findings.append(("thin", "medium", f"Jawaban tipis ({len(body.split())} kata)."))
        if expect_grounded:
            if not grounded:
                findings.append(("ungrounded", "high", "Tidak menyebut satu pun mekanisme produk."))
            elif not grounded_first:
                findings.append((
                    "grounding_late", "low",
                    "Menyebut produk hanya di kalimat lanjutan, bukan di rekomendasi pertama "
                    f"({', '.join(grounded)})."))
        elif grounded:
            findings.append((
                "unexpected_product_claim", "medium",
                "Menyebut mekanisme produk pada kasus yang tidak mengharapkan jawaban produk "
                f"(filler atau tanpa Host profile): {', '.join(grounded)}."))
        if CLIENT_VOICE_RE.search(body):
            findings.append(("role_inversion", "high", "Memakai suara Client, bukan Consultant."))
        invented = invented_signals(body)
        if invented:
            findings.append(("invented", "medium", f"Fitur generik tanpa dasar di profil Host: {', '.join(invented)}."))
        if "Speaker's move:" not in answer:
            findings.append(("no_preamble", "low", "Tidak ada baris 'Speaker's move:' (Inggris)."))
        lang = header_language(answer)
        if expect_language and lang and lang.lower() != expect_language.lower():
            findings.append(("language", "medium", f"Header bahasa {lang}, diharapkan {expect_language}."))
    # A filler trigger is a defect only when a reply was actually spent on it; a
    # skipped one is already covered by the `skipped` note above.
    if not skipped and is_filler(trigger):
        findings.append(("filler_trigger", "high", f"Pemicunya filler: {one_line(trigger, 40)!r}"))
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f[1], 9))
    # Three levels, so a low-severity observation does not read as a defect:
    # low-only is a note, anything medium/high is a real problem.
    severities = {f[1] for f in findings}
    if not findings:
        verdict = "OK"
    elif severities & {"high", "medium"}:
        verdict = "PERLU DIPERHATIKAN"
    else:
        verdict = "CATATAN"
    return {
        "verdict": verdict,
        "body": body,
        "preamble": preamble_of(answer),
        "header_language": header_language(answer),
        "matched_product_terms": grounded,
        "matched_product_terms_first_sentence": grounded_first,
        "matched_invention_terms": invented_signals(body),
        "expect_grounded": expect_grounded,
        "skipped": skipped,
        "latency_ms": latency_ms,
        "findings": [
            {"code": c, "severity": s, "note": n, "cause": FINDING_CAUSE.get(c, "")}
            for c, s, n in findings
        ],
    }


# --- Bagian A: recorded replay -------------------------------------------
def pair_triggers(session: dict) -> list:
    """Pair each gemini_result with the utterance run that triggered it."""
    trs = sorted(
        (t for t in (session.get("transcriptions") or []) if (t.get("text") or "").strip()),
        key=lambda t: t.get("timestamp", ""),
    )
    results = session.get("aireply_results") or []
    cases = []
    prev_ts = ""
    for i, r in enumerate(results):
        ts = r.get("timestamp", "")
        before = [t for t in trs if t.get("timestamp", "") <= ts]
        last = before[-1] if before else None
        window = []
        if last is not None:
            window = [t for t in before
                      if t.get("timestamp", "") > prev_ts
                      and t.get("source") == last.get("source")]
        window_text = " ".join((t.get("text") or "").strip() for t in window).strip()
        last_text = (last.get("text") or "").strip() if last else ""
        # The effective trigger is the merged window when we have one, else the raw
        # last fragment (a filler-only gap between two results still triggered a reply).
        effective = window_text or last_text
        latency = None
        if last is not None:
            try:
                t0 = datetime.fromisoformat(last["timestamp"])
                t1 = datetime.fromisoformat(ts)
                latency = int((t1 - t0).total_seconds() * 1000)
            except (KeyError, ValueError):
                latency = None
        cases.append({
            "id": f"A{i + 1}",
            "kind": "recorded",
            "timestamp": ts,
            "trigger_last": last_text,
            "trigger_source": last.get("source") if last else "",
            "trigger_window": window_text,
            "trigger_effective": effective,
            "answer": r.get("text") or "",
            "mode": r.get("mode") or "",
            "latency_ms": latency,
            "analysis": analyze(r.get("text") or "", effective,
                                expect_language="English", latency_ms=latency),
        })
        prev_ts = ts
    return cases


# --- Lampiran: prompt contract (deterministic, no model) ------------------
class _StubClient:
    """Captures what the worker sends and yields a canned reply."""

    def __init__(self, reply: str = "English Text: canned"):
        self.reply = reply
        self.calls = []

    def generate(self, system_instruction, messages, disable_reasoning=None):
        self.calls.append({"si": system_instruction, "messages": messages})
        return self.reply

    def generate_stream(self, system_instruction, messages, disable_reasoning=None):
        self.calls.append({"si": system_instruction, "messages": messages})
        if self.reply:
            yield self.reply


def capture_prompt(text: str, history: list, context) -> dict:
    """Run the real worker against a stub client; return the captured prompt."""
    original = gw.get_ai_client
    client = _StubClient()
    gw.get_ai_client = lambda: client
    try:
        worker = gw.GeminiAutoReplyWorker(
            text, "English", conversation_history=list(history),
            include_pronunciation=False, purpose=PURPOSE, host_role=HOST_ROLE,
            context=context,
        )
        worker.run()
    finally:
        gw.get_ai_client = original
    return client.calls[0] if client.calls else {"si": "", "messages": []}


def runtime_purpose(key: str):
    """The purpose as it *actually runs*: the seed, plus non-built-in file entries.

    Mirrors ``PurposeStore._load`` (schema 2): built-ins always come from
    ``BUILTIN_PURPOSES`` and a **stale on-disk copy is ignored**, so editing
    ``src/purposes.py`` is enough. Returns ``(purpose, stale_builtin_copy)``.
    """
    seed = copy.deepcopy(BUILTIN_PURPOSES.get(key, {}))
    try:
        with open(PURPOSES_PATH, encoding="utf-8") as f:
            disk = json.load(f)
    except (OSError, ValueError):
        disk = None
    if not isinstance(disk, dict):
        return seed, False
    wrapped = isinstance(disk.get("purposes"), dict)
    entries = disk["purposes"] if wrapped else disk
    if key in BUILTIN_PURPOSES:
        stale = key in entries and entries[key] != BUILTIN_PURPOSES[key]
        return seed, stale
    entry = entries.get(key)
    return (copy.deepcopy(entry) if isinstance(entry, dict) else seed), False


def _objective_lines(purpose: dict, role_key: str) -> list:
    return list((purpose.get("roles", {}) or {}).get(role_key, {}).get("objective") or [])


def _role_style(purpose: dict, role_key: str) -> dict:
    style = (purpose.get("roles", {}) or {}).get(role_key, {}).get("style")
    return style if isinstance(style, dict) else {}


def _answer_first(purpose: dict, role_key: str) -> bool:
    """Does the running prompt tell the model to answer before anything else?

    Answer-first lives in the per-role ``style`` block (rendered by
    ``gemini_worker._style_block``); older objectives may still carry the line.
    """
    style = _role_style(purpose, role_key)
    if "answer_first" in style:
        return bool(style["answer_first"])
    return any("answer" in line.lower() for line in _objective_lines(purpose, role_key))


def prompt_contract(session: dict, helpy: str, maya: str) -> dict:
    """The structural facts behind the symptoms — mirrors the offline witnesses."""
    conv = session.get("conversation") or []
    question = "How do we stop that from happening?"
    q_idx = -1
    for i in range(len(conv) - 1, -1, -1):
        if conv[i].get("role") != "host" and question.lower() in (conv[i].get("text") or "").lower():
            q_idx = i
            break

    with_ctx = capture_prompt(question, conv[: q_idx + 1] if q_idx >= 0 else conv,
                              {"host": helpy or "HOSTCTX", "speaker": maya})
    no_ctx = capture_prompt(question, conv[: q_idx + 1] if q_idx >= 0 else conv,
                            {"host": "", "speaker": ""})
    # A host turn landing after the question, before the debounce fires.
    trailing = capture_prompt(question, [
        {"role": "speaker", "text": question, "suggestion": ""},
        {"role": "host", "text": "Okay.", "suggestion": ""},
    ], {"host": helpy or "HOSTCTX", "speaker": maya})

    si = with_ctx["si"]
    # Strip the injected Host profile before searching: the 12 KB doc body itself
    # contains phrases like "source of truth" and would fool the detector.
    scrubbed = si.replace(helpy.strip(), "\u00abHOST_PROFILE\u00bb").lower() if helpy else si.lower()
    messages = with_ctx["messages"]
    q_count = sum(1 for m in messages if m.get("text") == question)
    trailing_q = sum(1 for m in trailing["messages"] if m.get("text") == question)
    runtime_consultation, stale_builtin_copy = runtime_purpose(PURPOSE)
    seed_purpose = BUILTIN_PURPOSES.get(PURPOSE, {})
    return {
        "grounding_rule_present": any(p in scrubbed for p in (
            "source of truth", "use the host profile", "from the host profile",
            "grounded in the host profile")),
        "grounding_first_sentence_rule": "FIRST sentence" in si,
        "no_context_anti_invention_rule": "do not invent product" in no_ctx["si"],
        "style_block_present": "\nStyle:\n" in si,
        "host_line_omitted_without_context": "Host profile" not in no_ctx["si"],
        # What the app really sends: the seed wins, the file only adds new entries.
        "answer_first_objective": _answer_first(runtime_consultation, "consultant"),
        "answer_first_objective_in_seed": _answer_first(seed_purpose, "consultant"),
        "stale_builtin_copy": stale_builtin_copy,
        # Phase 1 niche feature gates. Both are prompt no-ops while off (or while
        # nothing is tracked), so a reader comparing two reports needs to know
        # which side of the A/B each one was.
        "digest_enabled": bool(getattr(gw, "AUTO_REPLY_CONTEXT_DIGEST", False)),
        "objective_focus_absent": "Objective focus:" not in si,
        # Config-level, not per-run: whether JEV *could* run at all (flag + key).
        # Whether this run actually used it is in the metadata (``jev``).
        "jev_available": bool(DecisionClient().available),
        "history_starts_with_user": bool(messages) and messages[0].get("role") == "user",
        "question_sent_once": q_count == 1,
        "question_sent_once_with_trailing_host_turn": trailing_q == 1,
        "history_turns": len(messages),
        "recorded_turns": len(conv),
    }


CONTRACT_ROWS = [
    ("grounding_rule_present", "Ada aturan grounding yang mengikat Host profile ke jawaban",
     "cause 1 / F1"),
    ("grounding_first_sentence_rule", "Grounding menuntut mekanisme produk di kalimat **pertama**",
     "cause 1 / F1 (`grounding_late`)"),
    ("no_context_anti_invention_rule", "Tanpa Host profile, prompt melarang mengarang spesifik produk",
     "cause 1 / F1 (`invented` / L7)"),
    ("style_block_present", "Blok `Style:` per-role ada di prompt (approach/tone/length)",
     "persona style"),
    ("answer_first_objective", "Prompt yang **benar-benar berjalan** menyuruh menjawab dulu",
     "cause 3 / F2 — kini dari blok `Style:` per-role (fallback: baris objective)"),
    ("question_sent_once_with_trailing_host_turn", "Pertanyaan terkirim tepat sekali (walau ada host turn sesudahnya)",
     "cause 5 / _build_messages"),
    ("history_starts_with_user", "History prompt dimulai dengan turn 'user'",
     "cause 5 / _build_messages"),
    ("host_line_omitted_without_context", "Baris Host profile hilang saat user tidak memilih context",
     "kontrak (sudah benar)"),
    ("digest_enabled", "`AUTO_REPLY_CONTEXT_DIGEST` aktif (sesi digest ikut ke prompt)",
     "Phase 1 — opt-in, jadi ✅ di sini berarti run ini mengukur sisi digest"),
    ("objective_focus_absent", "Tanpa objective, prompt tidak memuat blok `Objective focus:`",
     "Phase 2 — blok objective hanya muncul saat ada objective terlacak"),
    ("jev_available", "JEV bisa jalan di checkout ini (`JEV_ENABLED` + key)",
     "konfigurasi — apakah run ini memakai JEV ada di Metadata (`jev`)"),
]


# --- Bagian B: live scenarios --------------------------------------------
def live_scenarios(session: dict, recorded_cases: list, repeat: int) -> list:
    """The live tier's scenario table, as report cases."""
    scenarios = []
    if recorded_cases:
        # Mirror _tmp_auto_reply_live_check.py's L1: the recorded question, replayed
        # with the conversation as it stood at trigger time.
        conv = session.get("conversation") or []
        q_idx = -1
        for i in range(len(conv) - 1, -1, -1):
            if conv[i].get("role") != "host" and \
                    "stop that from happening" in (conv[i].get("text") or "").lower():
                q_idx = i
                break
        question = conv[q_idx]["text"].strip() if q_idx >= 0 else recorded_cases[-1]["trigger_last"]
        history = conv[: q_idx + 1] if q_idx >= 0 else []
        scenarios.append({
            "id": "L1", "title": "Replay pertanyaan terekam yang gagal",
            "text": question, "history": history,
            "expect_language": "English", "context": "attached",
            "expect_grounded": True, "repeat": repeat,
        })
    scenarios += [
        {"id": "L2", "title": "Speaker bertanya — harus dijawab, bukan pertanyaan balik",
         "text": "How does your tool actually fix the handoffs?",
         "history": [{"role": "speaker", "text": "How does your tool actually fix the handoffs?", "suggestion": ""}],
         "expect_language": "English", "context": "attached", "expect_grounded": True},
        {"id": "L3", "title": "Pertanyaan produk — harus grounded di Host profile",
         "text": "How would your tool stop that constant back-and-forth?",
         "history": [{"role": "speaker", "text": "How would your tool stop that constant back-and-forth?", "suggestion": ""}],
         "expect_language": "English", "context": "attached", "expect_grounded": True},
        {"id": "L4", "title": "Ack lalu pertanyaan baru — harus tetap suara Consultant",
         "text": "How do we stop that from happening?",
         "history": [
             {"role": "speaker", "text": "how exactly would your tool stop that back-and-forth?", "suggestion": ""},
             {"role": "host", "text": "Helpy captures both sides into a shared brief.", "suggestion": ""},
             {"role": "speaker", "text": "Exactly.", "suggestion": ""},
             {"role": "speaker", "text": "You nailed it.", "suggestion": ""},
             {"role": "speaker", "text": "How do we stop that from happening?", "suggestion": ""},
         ],
         "expect_language": "English", "context": "attached", "expect_grounded": True},
        {"id": "L5", "title": "Utterance filler saja ('Okay.')",
         "text": "Okay.",
         "history": [{"role": "speaker", "text": "Okay.", "suggestion": ""}],
         "expect_language": "English", "context": "attached", "expect_grounded": False},
        {"id": "L7", "title": "Tanpa Host context — jangan mengarang klaim produk",
         "text": "How does it work?",
         "history": [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
         "expect_language": "English", "context": "none", "expect_grounded": False},
        {"id": "L10", "title": "Cross-language — Speaker berbahasa Indonesia",
         "text": "Bagaimana caranya supaya brief tidak hilang saat serah terima?",
         "history": [{"role": "speaker",
                      "text": "Bagaimana caranya supaya brief tidak hilang saat serah terima?",
                      "suggestion": ""}],
         "expect_language": "Indonesian", "context": "attached", "expect_grounded": True},
    ]
    return scenarios


class _LogCapture(logging.Handler):
    """Collect ``gemini_worker`` log messages for the duration of one live case.

    The Other flow (persona synthesis) is only observable through its log line —
    it does not emit a distinct signal, and in the harness it cannot register a
    persona (no ``purpose_store`` is passed), so ``Learned new persona`` never
    appears. Capturing the record is the least invasive way to count how often
    the JEV path escalates.
    """

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.messages = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:  # noqa: BLE001 - never let logging break a report
            pass

    def count(self, needle: str) -> int:
        return sum(1 for m in self.messages if needle in m)


def run_live(scenario: dict, helpy: str, maya: str, jev: bool = False,
             role: str = HOST_ROLE) -> dict:
    context = None if scenario["context"] == "attached" else {"host": "", "speaker": ""}
    if context is None:
        context = {"host": helpy or "HOSTCTX", "speaker": maya}
    history = scenario["history"]
    if history is None:
        history = []
    out = {"text": "", "error": "", "chunks": [], "skipped": "", "status": ""}
    capture = _LogCapture()
    worker_logger = logging.getLogger("src.gemini_worker")
    # ``logger.info`` is dropped when the logger's effective level is above INFO,
    # and these harnesses never configure logging (the root default is WARNING),
    # so the level has to be forced for the capture to see anything.
    previous_level = worker_logger.level
    worker_logger.setLevel(logging.INFO)
    worker_logger.addHandler(capture)
    worker = gw.GeminiAutoReplyWorker(
        scenario["text"], "English", conversation_history=list(history),
        include_pronunciation=False, purpose=PURPOSE, host_role=role,
        context=context, jev_enabled=jev,
    )
    worker.result.connect(lambda t: out.__setitem__("text", t))
    worker.error.connect(lambda t: out.__setitem__("error", t))
    worker.chunk.connect(lambda t: out["chunks"].append(t))
    worker.skipped.connect(lambda t: out.__setitem__("skipped", t))
    worker.status.connect(lambda t: out.__setitem__("status", t))
    t0 = time.monotonic()
    try:
        worker.run()
    finally:
        worker_logger.removeHandler(capture)
        worker_logger.setLevel(previous_level)
    latency = round((time.monotonic() - t0) * 1000)
    analysis = analyze(out["text"], scenario["text"],
                       expect_language=scenario["expect_language"], latency_ms=latency,
                       expect_grounded=scenario["expect_grounded"],
                       skipped=out.get("skipped", ""))
    if out["error"] and not out["text"]:
        analysis["findings"].insert(0, {
            "code": "provider_error", "severity": "high",
            "note": out["error"], "cause": "bukan bug pipeline",
        })
        analysis["verdict"] = "PERLU DIPERHATIKAN"
    return {
        "id": scenario["id"],
        "kind": "live",
        "title": scenario["title"],
        "trigger_last": scenario["text"],
        "trigger_window": scenario["text"],
        "trigger_effective": scenario["text"],
        "trigger_source": "speaker",
        "context": scenario["context"],
        "answer": out["text"],
        "error": out["error"],
        "skipped": out.get("skipped", ""),
        "status": out.get("status", ""),
        "jev": bool(jev),
        "role": role,
        "escalated": capture.count("Other flow triggered") > 0,
        "role_rejected": capture.count("JEV: no reply needed") > 0,
        "latency_ms": latency,
        "stream_chunks": len(out["chunks"]),
        "analysis": analysis,
    }


# --- rendering -----------------------------------------------------------
def summary_rows(cases: list) -> list:
    rows = []
    for c in cases:
        a = c["analysis"]
        reasons = "; ".join(f["code"] for f in a["findings"]) or "—"
        latency = f"{a['latency_ms']} ms" if a["latency_ms"] is not None else "—"
        rows.append((c["id"], c["kind"], one_line(c["trigger_effective"], 60),
                     a["verdict"], reasons, latency))
    return rows


def render_markdown(meta: dict, recorded: list, live: list, contract: dict,
                    aggregate: dict, note: str) -> str:
    L = []
    L.append("# Laporan Auto-Reply (AI Suggestion)")
    L.append("")
    L.append("Laporan ini menjawab tiga hal per kasus: **apa yang ditanyakan**, **apa jawaban AI**, dan "
             "**kenapa jawaban itu tepat atau tidak tepat**. Analisanya deterministik (rule, bukan penilaian "
             "model), jadi verdict-nya bisa diulang dan dibandingkan antar-run.")
    L.append("")
    L.append("## Metadata")
    L.append("")
    L.append(f"- Dibuat: `{meta['generated_at']}`")
    L.append(f"- Provider: `{meta['provider']}` · model: `{meta['model']}` · base: `{meta['base_url']}` · "
             f"reasoning dimatikan: `{meta['disable_reasoning']}`")
    L.append(f"- Git: `{meta['git_rev']}`")
    L.append(f"- Sumber: `{meta.get('session_path', 'sessions/current.json')}` "
             f"({meta['recorded_turns']} turn, {meta['recorded_results']} jawaban terekam) · "
             f"`docs/helpy.context.txt` (Host) · `maya.context.txt` (Speaker)")
    L.append(f"- Kasus: Bagian A = {len(recorded)}, Bagian B = {len(live)}")
    L.append(f"- Bagian B: gerbang JEV `{'AKTIF' if meta.get('jev') else 'mati'}` · "
             f"peran 'I am:' `{meta.get('role', HOST_ROLE)}`")
    if note:
        L.append(f"- Catatan: {note}")
    L.append("")

    for title, cases, intro in (
        ("## Bagian A — Replay sesi terekam",
         recorded,
         "Setiap jawaban nyata dari `aireply_results` dipasangkan dengan pemicunya. "
         "Latensi di sini **perkiraan** (selisih timestamp transkrip vs hasil), bukan latensi model."),
        ("## Bagian B — Skenario live",
         live,
         "Skenario yang sama dengan `_tmp_auto_reply_live_check.py`. Latensi di sini latensi model asli."),
    ):
        L.append(title)
        L.append("")
        L.append(intro)
        L.append("")
        if not cases:
            L.append("_Dilewati._")
            L.append("")
            continue
        L.append("| # | Sumber | Pemicu | Verdict | Temuan | Latensi |")
        L.append("|---|--------|--------|---------|--------|---------|")
        for row in summary_rows(cases):
            L.append(f"| {row[0]} | {row[1]} | {md_escape(row[2])} | **{row[3]}** | {row[4]} | {row[5]} |")
        L.append("")
        for c in cases:
            a = c["analysis"]
            L.append(f"### {c['id']} — {one_line(c['trigger_window'], 90)}")
            L.append("")
            if c.get("title"):
                L.append(f"*{c['title']}*")
                L.append("")
            L.append(f"- **Waktu/sumber:** `{c.get('timestamp', '—')}` · pemicu dari `{c.get('trigger_source')}`"
                     + (f" · mode `{c.get('mode')}`" if c.get("mode") else ""))
            if c.get("trigger_window"):
                L.append(f"- **Window utterance:** {one_line(c['trigger_window'], 240)}")
            if c.get("trigger_last"):
                L.append(f"- **Fragmen terakhir:** {one_line(c['trigger_last'], 160)}")
            if a["preamble"]:
                L.append(f"- **Preamble:** {one_line(a['preamble'], 200)}")
            L.append(f"- **Verdict:** **{a['verdict']}**")
            if a["matched_product_terms"]:
                first_hit = a["matched_product_terms_first_sentence"]
                L.append(f"- **Sebut produk:** {', '.join(a['matched_product_terms'])}"
                         + (f" · di kalimat pertama: {', '.join(first_hit)}" if first_hit
                            else " · **tidak di kalimat pertama**"))
            if c.get("skipped"):
                L.append(f"- **Skip:** {c['skipped']}")
            if c.get("status"):
                L.append(f"- **Status:** {c['status']}")
            if c.get("escalated"):
                L.append("- **Eskalasi:** Other flow (persona synthesis) — panggilan LLM tambahan")
            L.append("")
            L.append("**Jawaban AI:**")
            L.append("")
            L.append("```text")
            L.append((c["answer"] or "(tidak ada jawaban)").strip())
            L.append("```")
            L.append("")
            L.append("**Analisa:**")
            L.append("")
            if not a["findings"]:
                L.append("- Tidak ada temuan: jawaban memenuhi semua kontrak deterministik.")
            for f in a["findings"]:
                L.append(f"- `{f['code']}` ({f['severity']}) — {f['note']}"
                         + (f" → **{f['cause']}**" if f["cause"] else ""))
            L.append("")

    L.append("## Bagian C — Analisa agregat")
    L.append("")
    L.append("Verdict: `OK` (tidak ada temuan) · `CATATAN` (hanya temuan severity rendah) · "
             "`PERLU DIPERHATIKAN` (ada temuan medium/tinggi).")
    L.append("")
    L.append(f"- Kasus: {aggregate['total']} · " + " · ".join(
        f"{k}={v}" for k, v in sorted(aggregate["verdicts"].items())))
    if aggregate["latency"]:
        lat = aggregate["latency"]
        L.append(f"- Latensi live: min {lat['min']} ms · rata-rata {lat['avg']} ms · max {lat['max']} ms "
                 f"({lat['n']} kasus)")
    L.append("")
    L.append("| Temuan | Jumlah | Cause |")
    L.append("|--------|--------|-------|")
    for code, count, cause in aggregate["findings"]:
        L.append(f"| `{code}` | {count} | {cause or '—'} |")
    L.append("")
    if aggregate["trigger_fillers"]:
        L.append(f"- Pemicu berupa filler: {', '.join(aggregate['trigger_fillers'])}")
        L.append("")
    jev = aggregate.get("jev") or {}
    if jev.get("enabled"):
        L.append("**Gerbang JEV (Bagian B).** Skip di sini adalah **keputusan gerbang**, bukan cacat: "
                 "`should_reply` menilai Speaker belum butuh jawaban.")
        L.append("")
        L.append(f"- Peran 'I am:' `{jev.get('role')}`")
        L.append(f"- Ditahan gerbang: {', '.join(jev.get('suppressed') or []) or '—'}")
        L.append(f"- Eskalasi ke Other flow (panggilan LLM tambahan): "
                 f"{', '.join(jev.get('escalated') or []) or '—'}")
        if jev.get("status"):
            L.append("- Status per kasus: " + " · ".join(
                f"`{cid}` {st}" for cid, st in jev["status"].items()))
        L.append("")
    elif live:
        L.append("_Bagian B berjalan **tanpa** gerbang JEV (worker dibangun dengan "
                 "`jev_enabled=False`). Pakai `--jev` untuk mengukurnya._")
        L.append("")
    L.append("Catatan keterbatasan detektor (baca verdict sebagai sinyal, bukan putusan):")
    L.append("")
    L.append("- `invented` kini menambal dua sisi yang sudah terukur: klaim kemampuan "
             "(\"it syncs\", \"automatically\", \"you get a weekly report\", \"free trial\") ikut "
             "terdeteksi, dan istilah ambigu (`api`, `crm`, `platform`, `pipeline`) tidak lagi "
             "ditandai bila kalimatnya sudah menyebut produk asli (\"Helpy's consulting pipeline\"). "
             "Tetap sinyal, bukan putusan — selalu baca istilah yang dilaporkan.")
    L.append("- `grounding_late` sengaja ber-severity rendah: jawaban masih menyebut produk, hanya tidak "
             "di rekomendasi pertama.")
    L.append("")

    L.append("## Lampiran — Kontrak prompt (deterministik)")
    L.append("")
    L.append("Apa yang sebenarnya kita kirim ke model. Ini pengikat antara gejala di atas dan penyebab "
             "strukturalnya; angkanya tidak berubah antar-run karena tidak memanggil model.")
    L.append("")
    L.append("| Kontrak | Status | Cause bila belum terpenuhi |")
    L.append("|---------|--------|----------------------------|")
    for key, label, cause in CONTRACT_ROWS:
        ok = bool(contract.get(key))
        L.append(f"| {label} | {'✅ ya' if ok else '❌ belum'} | {cause} |")
    L.append("")
    L.append(f"- Turn history yang dikirim: {contract.get('history_turns', 0)} "
             f"(dari {contract.get('recorded_turns', 0)} turn terekam)")
    if contract.get("stale_builtin_copy"):
        L.append("")
        L.append("- ⚠️ Salinan built-in yang **basi** terdeteksi di `purposes.json`. Sejak schema 2 "
                 "salinan itu diabaikan: built-in selalu dibaca dari `src/purposes.py`, dan file "
                 "hanya menyimpan entri non-built-in. Refresh dengan menjalankan app sekali "
                 "(store menulis ulang saat menyimpan) atau hapus `purposes.json`.")
    L.append("")
    return "\n".join(L) + "\n"


def build_aggregate(recorded: list, live: list) -> dict:
    cases = recorded + live
    counts = {}
    for c in cases:
        for f in c["analysis"]["findings"]:
            counts[f["code"]] = counts.get(f["code"], 0) + 1
    findings = sorted(
        ((code, n, FINDING_CAUSE.get(code, "")) for code, n in counts.items()),
        key=lambda t: (-t[1], t[0]),
    )
    lats = [c["latency_ms"] for c in live if c["latency_ms"] is not None]
    latency = None
    if lats:
        latency = {"n": len(lats), "min": min(lats), "max": max(lats), "avg": sum(lats) // len(lats)}
    fillers = [c["id"] for c in cases if is_filler(c["trigger_effective"])]
    verdicts = {}
    for c in cases:
        verdicts[c["analysis"]["verdict"]] = verdicts.get(c["analysis"]["verdict"], 0) + 1
    # JEV-specific behaviour. Suppression is a legitimate outcome (the gate
    # decided the Speaker needs nothing), not a defect, so it is counted here
    # rather than left to the finding table.
    suppressed = [c["id"] for c in live if c.get("skipped")]
    escalated = [c["id"] for c in live if c.get("escalated")]
    jev = {
        "enabled": any(c.get("jev") for c in live),
        "role": next((c.get("role") for c in live if c.get("jev")), None),
        "suppressed": suppressed,
        "escalated": escalated,
        "status": {c["id"]: c.get("status", "") for c in live if c.get("status")},
    }
    return {
        "total": len(cases),
        "verdicts": verdicts,
        "findings": findings,
        "latency": latency,
        "trigger_fillers": fillers,
        "jev": jev,
    }


def git_rev() -> str:
    import subprocess  # noqa: PLC0415
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the auto-reply report.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="path Markdown (default: %(default)s)")
    parser.add_argument("--json", dest="json_path", default=DEFAULT_JSON,
                        help="path JSON sidecar (default: %(default)s)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="ulangi skenario L1 sebanyak N kali (default: %(default)s)")
    parser.add_argument("--recorded-only", action="store_true",
                        help="paksa lewati Bagian B walau AUTO_REPLY_LIVE_TESTS=1")
    parser.add_argument("--session", default=SESSION_PATH,
                        help="sesi untuk Bagian A (default: %(default)s); gunakan file replay "
                             "hasil _tmp_auto_reply_record.py untuk mengukur prompt saat ini")
    parser.add_argument("--jev", action="store_true",
                        help="jalankan Bagian B dengan gerbang JEV aktif (jev_enabled=True). "
                             "Tanpa ini run mengukur jalur non-JEV, walau JEV_ENABLED=true di .env")
    parser.add_argument("--role", default=HOST_ROLE, choices=ROLES,
                        help="peran 'I am:' untuk Bagian B (default: %(default)s). Pakai "
                             "'smart' untuk mengukur adopsi peran oleh JEV")
    args = parser.parse_args()

    # JEV has to be requested explicitly: the worker's ``jev_enabled`` defaults to
    # False, so ``JEV_ENABLED=true`` in .env alone never reaches this harness.
    jev = bool(args.jev or os.environ.get("AUTO_REPLY_JEV_TESTS") == "1")
    role = args.role

    session = load_session(args.session)
    helpy = read_file("docs", "helpy.context.txt")
    maya = read_file("maya.context.txt") or "Her name is Maya."

    recorded = pair_triggers(session)

    live = []
    note = ""
    live_enabled = os.environ.get("AUTO_REPLY_LIVE_TESTS") == "1" and not args.recorded_only
    if live_enabled:
        try:
            gw.get_ai_client()  # force a config error now, not mid-report
        except Exception as e:  # noqa: BLE001 - any build failure means "skip"
            live_enabled = False
            note = f"Bagian B dilewati: provider tidak bisa dibangun ({type(e).__name__}: {e})."
        else:
            for scenario in live_scenarios(session, recorded, max(1, args.repeat)):
                live.append(run_live(scenario, helpy, maya, jev=jev, role=role))
    else:
        note = ("Bagian B dilewati. Jalankan `AUTO_REPLY_LIVE_TESTS=1 venv/bin/python "
                "tools/auto_reply_report.py` untuk menjalankannya (memanggil model asli).")

    contract = prompt_contract(session, helpy, maya)
    aggregate = build_aggregate(recorded, live)
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": AI_PROVIDER,
        "model": AI_MODEL,
        "base_url": AI_BASE_URL,
        "disable_reasoning": DISABLE_MODEL_REASONING,
        "git_rev": git_rev(),
        "session_path": os.path.relpath(os.path.abspath(args.session), REPO),
        "recorded_turns": len(session.get("conversation") or []),
        "recorded_results": len(session.get("aireply_results") or []),
        # The two live-tier axes. A report is only comparable to another report
        # that ran with the same values here.
        "jev": jev,
        "role": role,
    }

    markdown = render_markdown(meta, recorded, live, contract, aggregate, note)
    for path in (args.out, args.json_path):
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(markdown)
    payload = {
        "meta": meta, "note": note, "recorded": recorded, "live": live,
        "contract": contract, "aggregate": aggregate,
    }
    with open(args.json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Markdown : {args.out}")
    print(f"JSON     : {args.json_path}")
    print(f"Kasus    : A={len(recorded)} B={len(live)} · " + " · ".join(
        f"{k}={v}" for k, v in sorted(aggregate["verdicts"].items())))
    if note:
        print(f"Catatan  : {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
