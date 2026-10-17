"""Throwaway checks for the bullet-points delta contract + windows (no AI calls).

Exercises ``BulletPointsController`` directly with the worker start stubbed out,
so nothing hits the network:

  (a) ``_merge_new_items`` drops exact duplicates and near-duplicates
  (b) ``_build_user_message`` differs between append (incremental) and rebuild, and
      names the locked block when a rebuild carries locked points
  (c) an append result grows the list and fills from_index/to_index correctly
  (d) a rebuild result resets ``bullet_windows``
  (e) a payload with no ``mode`` defaults to "replace"
  (f) locks: toggle by index/text, pin locked items on top of a rebuild, and keep
      ``_locked`` index-aligned through appends/load_state/reset
  (g) speaker-profile locks: toggle a scalar and a list item, keep a locked value
      verbatim through append/rebuild/empty answers, and name it in the prompt

    venv/bin/python _tmp_bullet_delta_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src.bullet_points_worker import BulletPointsWorker  # noqa: E402
from src.config import SPEAKER_MAX_LIST_ITEMS  # noqa: E402
from src.controllers.bullet_points_controller import BulletPointsController  # noqa: E402

PASSED = []
FAILED = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def new_controller() -> BulletPointsController:
    """A controller whose worker start is stubbed (records, never runs)."""
    controller = BulletPointsController()
    controller._fake_calls = []

    def fake_start_worker(current_bullets, current_speaker, lines, rebuild=False,
                          locked_speaker=None):
        controller._fake_calls.append(
            {"bullets": list(current_bullets), "lines": list(lines), "rebuild": rebuild,
             "locked_speaker": dict(locked_speaker or {})}
        )

    controller._start_worker = fake_start_worker
    return controller


def main() -> int:
    QCoreApplication.instance() or QCoreApplication(sys.argv)

    # --- (a) exact + near duplicate merge --------------------------------
    print("\n[merge]")
    controller = new_controller()
    existing = ["Budget belum ada", "Butuh dua kandidat tambahan"]
    merged = controller._merge_new_items(
        existing,
        [
            "Budget belum ada",                     # exact duplicate (same case)
            "budget belum ada!",                    # duplicate after normalization
            "Butuh dua kandidat tambahan segera",   # near duplicate (Jaccard 4/5 = 0.8)
            "Kandidat baru dibutuhkan",             # genuinely new
        ],
    )
    check("exact duplicate dropped", merged.count("Budget belum ada") == 1, f"got {merged}")
    check("normalized duplicate dropped",
          sum(1 for i in merged if i.casefold().startswith("budget belum")) == 1,
          f"got {merged}")
    check("near duplicate dropped", not any("segera" in i for i in merged), f"got {merged}")
    check("genuinely new bullet kept", "Kandidat baru dibutuhkan" in merged, f"got {merged}")
    check("existing order preserved", merged[:2] == existing, f"got {merged}")

    # A phrase whose tokens are the same count but differ by one word (0.667)
    # must NOT be merged — the guard is deliberately conservative.
    distinct = controller._merge_new_items(["Budget belum ada"], ["Budget sudah ada"])
    check("low-overlap phrases are kept separate", len(distinct) == 2, f"got {distinct}")

    # --- (b) mode-aware user message -------------------------------------
    print("\n[prompt]")
    append_msg = BulletPointsWorker(
        ["old point"], {"name": "Ada"}, [("speaker", "hello", "t1")], rebuild=False
    )._build_user_message()
    rebuild_msg = BulletPointsWorker(
        [], {}, [("speaker", "hello", "t1")], rebuild=True
    )._build_user_message()
    check("append message carries the current list",
          "old point" in append_msg and "ONLY new bullets" in append_msg, append_msg)
    check("rebuild message asks for the complete list",
          "COMPLETE bullet list" in rebuild_msg, rebuild_msg)
    check("append and rebuild messages differ", append_msg != rebuild_msg)
    check("3-tuple lines render (source + text)",
          "[speaker] hello" in append_msg and "t1" not in append_msg, append_msg)
    check("2-tuple lines still render",
          "[host] hai" in BulletPointsWorker([], {}, [("host", "hai")])._build_user_message())

    locked_msg = BulletPointsWorker(
        ["keep me", "keep me too"], {}, [("speaker", "hello", "t1")], rebuild=True
    )._build_user_message()
    check("rebuild with locks names the locked block",
          "Locked bullet points" in locked_msg and "keep me" in locked_msg, locked_msg)
    check("rebuild with locks asks only for the uncovered points",
          "NOT already covered" in locked_msg and "COMPLETE bullet list" not in locked_msg,
          locked_msg)

    # --- (c) append grows the list + window indices ----------------------
    print("\n[append]")
    controller = new_controller()
    controller.add_line("speaker", "first line")
    controller.add_line("host", "second line")
    controller._maybe_flush(force=True)
    check("flush captures an inflight window",
          controller._inflight_window is not None
          and controller._inflight_window["mode"] == "auto"
          and controller._inflight_window["lines"] == 2,
          f"got {controller._inflight_window}")
    controller._on_result({"items": ["point one", "point two"], "speaker": {}, "mode": "append"})
    check("append adds the new bullets", controller._bullets == ["point one", "point two"],
          f"got {controller._bullets}")
    first = controller._bullet_windows[0]
    check("first window maps indices 0..1 and mode=auto",
          len(controller._bullet_windows) == 1 and first["from_index"] == 0
          and first["to_index"] == 1 and first["mode"] == "auto" and first["lines"] == 2
          and bool(first["start"]) and bool(first["end"]),
          f"got {controller._bullet_windows}")

    controller.add_line("speaker", "third line")
    controller._maybe_flush(force=True)
    controller._on_result({"items": ["point three"], "speaker": {}, "mode": "append"})
    check("second append grows the list",
          controller._bullets == ["point one", "point two", "point three"],
          f"got {controller._bullets}")
    last = controller._bullet_windows[-1]
    check("second window maps indices 2..2",
          last["from_index"] == 2 and last["to_index"] == 2, f"got {last}")

    controller.add_line("speaker", "fourth line")
    controller._maybe_flush(force=True)
    controller._on_result({"items": [], "speaker": {}, "mode": "append"})
    check("no window is recorded when nothing is new", len(controller._bullet_windows) == 2,
          f"got {len(controller._bullet_windows)}")

    controller.add_line("speaker", "fifth line")
    controller._maybe_flush(force=True)
    controller._on_result({"items": ["point one"], "speaker": {}, "mode": "append"})
    check("duplicates from the model do not inflate the list",
          controller._bullets == ["point one", "point two", "point three"],
          f"got {controller._bullets}")
    check("a duplicate append records no window", len(controller._bullet_windows) == 2,
          f"got {controller._bullet_windows}")

    # --- (d) rebuild resets the windows ----------------------------------
    print("\n[rebuild]")
    controller.hard_regenerate([
        ("speaker", "first line", "2026-10-12T10:00:00.0"),
        ("host", "second line", "2026-10-12T10:05:00.0"),
    ])
    check("hard_regenerate records a rebuild window",
          controller._inflight_window is not None
          and controller._inflight_window["mode"] == "rebuild",
          f"got {controller._inflight_window}")
    controller._on_result({
        "items": ["rebuilt one", "rebuilt two", "rebuilt three"],
        "speaker": {"name": "Ada"},
        "mode": "replace",
    })
    check("rebuild replaces the list",
          controller._bullets == ["rebuilt one", "rebuilt two", "rebuilt three"],
          f"got {controller._bullets}")
    check("rebuild resets bullet_windows to one entry", len(controller._bullet_windows) == 1,
          f"got {controller._bullet_windows}")
    rebuilt = controller._bullet_windows[0]
    check("rebuild window spans the whole list and keeps mode=rebuild",
          rebuilt["mode"] == "rebuild" and rebuilt["from_index"] == 0 and rebuilt["to_index"] == 2,
          f"got {rebuilt}")
    check("rebuild window carries the transcript time range",
          rebuilt["start"] == "2026-10-12T10:00:00.0" and rebuilt["end"] == "2026-10-12T10:05:00.0",
          f"got {rebuilt}")

    # --- (e) legacy payload without mode ---------------------------------
    print("\n[mode default]")
    controller._on_result({"items": ["plain"], "speaker": {}})
    check("a payload with no mode defaults to replace",
          controller._bullets == ["plain"] and len(controller._bullet_windows) == 0,
          f"got bullets={controller._bullets} windows={controller._bullet_windows}")

    # --- reset / load_state parity ---------------------------------------
    print("\n[state]")
    controller.reset()
    check("reset clears the windows", controller._bullets == [] and controller._bullet_windows == [])
    controller.load_state(["a"], {"name": "Ada"}, [{"mode": "auto", "from_index": 0, "to_index": 0}])
    check("load_state seeds the windows",
          controller._bullets == ["a"] and len(controller._bullet_windows) == 1
          and controller._speaker == {"name": "Ada"},
          f"got {controller._bullet_windows}")
    controller.load_state([str(i) for i in range(80)])
    check("load_state does not cap the list", len(controller._bullets) == 80,
          f"got {len(controller._bullets)}")

    # --- (f) locks --------------------------------------------------------
    print("\n[locks]")
    controller = new_controller()
    controller.load_state(["alpha", "beta", "gamma"])
    check("load_state defaults missing locks to all False",
          controller._locked == [False, False, False], f"got {controller._locked}")
    check("set_lock by index toggles",
          controller.set_lock(index=1) is True and controller._locked == [False, True, False],
          f"got {controller._locked}")
    check("locked_items reflects the flag", controller.locked_items() == ["beta"],
          f"got {controller.locked_items()}")
    check("set_lock by text resolves the item",
          controller.set_lock(text="gamma", locked=True) is True
          and controller._locked == [False, True, True],
          f"got {controller._locked}")
    check("set_lock with the same value is a no-op",
          controller.set_lock(index=1, locked=True) is False)
    check("set_lock on a missing item returns False",
          controller.set_lock(text="nope") is False and controller.set_lock(index=99) is False)
    controller.load_state(["x", "y", "z"], locks=[True])
    check("load_state pads a short locks list with False",
          controller._locked == [True, False, False],
          f"got {controller._locked}")

    # Rebuild keeps the locked items verbatim on top, in order.
    controller.load_state(["beta", "gamma", "delta"], locks=[True, True, False])
    controller.hard_regenerate([("speaker", "hi", "t1")])
    check("rebuild passes the locked items to the worker",
          controller._fake_calls[-1]["bullets"] == ["beta", "gamma"],
          f"got {controller._fake_calls[-1]}")
    controller._on_result({"items": ["ai one", "ai two"], "speaker": {}, "mode": "replace"})
    check("rebuild puts locked items first then the AI's points",
          controller._bullets == ["beta", "gamma", "ai one", "ai two"],
          f"got {controller._bullets}")
    check("rebuild sets the lock flags [True,True,False,False]",
          controller._locked == [True, True, False, False], f"got {controller._locked}")

    controller.add_line("speaker", "new line")
    controller._maybe_flush(force=True)
    controller._on_result({"items": ["ai three"], "speaker": {}, "mode": "append"})
    check("an append pads the lock flags with False",
          controller._bullets == ["beta", "gamma", "ai one", "ai two", "ai three"]
          and controller._locked == [True, True, False, False, False],
          f"got bullets={controller._bullets} locks={controller._locked}")

    controller.load_state(["keep"], locks=[True])
    controller.reset()
    check("reset clears the locks",
          controller._locked == [] and controller.locked_items() == [],
          f"got {controller._locked}")

    # --- (g) speaker-profile locks ---------------------------------------
    print("\n[speaker locks]")
    PROFILE = {
        "name": "Maya", "location": "Jakarta", "occupation": "Head of Ops",
        "interests": ["coffee", "running"],
        "goals": ["cut onboarding time"],
        "pain_points": ["briefs get lost"],
        "facts": ["runs a 12-person team"],
    }
    speaker = new_controller()
    speaker.load_state([], PROFILE)
    check("load_state pads the speaker locks to the profile shape",
          speaker.get_speaker_locks()["name"] is False
          and speaker.get_speaker_locks()["interests"] == [False, False],
          f"got {speaker.get_speaker_locks()}")
    check("nothing is locked to begin with", speaker.locked_speaker() == {},
          f"got {speaker.locked_speaker()}")
    check("locking a scalar field works",
          speaker.set_speaker_lock(field="name", locked=True) is True
          and speaker.get_speaker_locks()["name"] is True)
    blank = new_controller()
    blank.load_state([], {"name": ""})
    check("locking an empty scalar is refused",
          blank.set_speaker_lock(field="name", locked=True) is False)
    check("locking a list item by text works",
          speaker.set_speaker_lock(field="interests", item="coffee", locked=True) is True
          and speaker.get_speaker_locks()["interests"] == [True, False],
          f"got {speaker.get_speaker_locks()['interests']}")
    check("locking the same value again is a no-op",
          speaker.set_speaker_lock(field="interests", item="coffee", locked=True) is False)
    check("an unknown field is refused",
          speaker.set_speaker_lock(field="nickname", locked=True) is False)
    check("a missing list item is refused",
          speaker.set_speaker_lock(field="goals", item="nope", locked=True) is False)
    check("locked_speaker names only the locked parts",
          speaker.locked_speaker() == {"name": "Maya", "interests": ["coffee"]},
          f"got {speaker.locked_speaker()}")

    # A locked scalar survives an AI answer that changes it.
    speaker._on_result({"items": [], "mode": "append", "speaker": {
        "name": "Not Maya", "location": "Bandung", "occupation": "CTO",
        "interests": ["rowing"], "goals": [], "pain_points": [], "facts": [],
    }})
    check("a locked scalar keeps its value through an AI update",
          speaker._speaker["name"] == "Maya", f"got {speaker._speaker['name']}")
    check("an unlocked scalar takes the AI's value",
          speaker._speaker["location"] == "Bandung", f"got {speaker._speaker['location']}")
    check("a locked list item is kept and the AI's new one is added",
          speaker._speaker["interests"] == ["coffee", "rowing"],
          f"got {speaker._speaker['interests']}")
    check("the merged list keeps the lock flags aligned",
          speaker.get_speaker_locks()["interests"] == [True, False],
          f"got {speaker.get_speaker_locks()['interests']}")

    # A locked value cannot be dropped by an empty AI answer either.
    speaker._on_result({"items": [], "mode": "append", "speaker": {}})
    check("a locked scalar survives an empty AI profile",
          speaker._speaker["name"] == "Maya", f"got {speaker._speaker}")
    check("a locked list item survives an empty AI profile",
          speaker._speaker["interests"] == ["coffee"],
          f"got {speaker._speaker['interests']}")

    # A rebuild hands the locked profile to the worker and keeps it verbatim.
    speaker.load_state([], PROFILE, speaker_locks=None)
    speaker.set_speaker_lock(field="name", locked=True)
    speaker.set_speaker_lock(field="pain_points", item="briefs get lost", locked=True)
    speaker.hard_regenerate([("speaker", "hi", "t1")])
    check("a rebuild passes the locked profile to the worker",
          speaker._fake_calls[-1]["locked_speaker"] == {
              "name": "Maya", "pain_points": ["briefs get lost"]},
          f"got {speaker._fake_calls[-1]['locked_speaker']}")
    speaker._on_result({"items": [], "mode": "replace", "speaker": {
        "name": "Someone else", "occupation": "Head of Ops",
        "pain_points": ["something new"], "interests": [], "goals": [], "facts": [],
        "location": "Jakarta",
    }})
    check("a rebuild cannot reword a locked scalar",
          speaker._speaker["name"] == "Maya", f"got {speaker._speaker['name']}")
    check("a rebuild cannot drop a locked list item",
          speaker._speaker["pain_points"] == ["briefs get lost", "something new"],
          f"got {speaker._speaker['pain_points']}")

    # A locked item outranks the per-list cap (never dropped to make room).
    capped = new_controller()
    capped.load_state([], {"goals": ["g0", "g1", "g2"]},
                      speaker_locks={"goals": [True, True, True]})
    capped._on_result({"items": [], "mode": "append", "speaker": {
        "goals": [f"new {i}" for i in range(12)], "name": "", "location": "",
        "occupation": "", "interests": [], "pain_points": [], "facts": [],
    }})
    check("a locked list item is never dropped by the list cap",
          capped._speaker["goals"][:3] == ["g0", "g1", "g2"]
          and len(capped._speaker["goals"]) == SPEAKER_MAX_LIST_ITEMS,
          f"got {capped._speaker['goals']}")
    check("the cap keeps the lock flags aligned",
          capped.get_speaker_locks()["goals"][:3] == [True, True, True]
          and len(capped.get_speaker_locks()["goals"]) == SPEAKER_MAX_LIST_ITEMS,
          f"got {capped.get_speaker_locks()['goals']}")

    # The worker message names the locked profile (rebuild and incremental).
    rebuild_worker = BulletPointsWorker([], {}, [("speaker", "hi", "t1")], rebuild=True,
                                        locked_speaker={"name": "Maya"})
    check("the rebuild prompt carries the locked-profile block",
          "Locked speaker profile" in rebuild_worker._build_user_message()
          and "Maya" in rebuild_worker._build_user_message())
    append_worker = BulletPointsWorker([], {}, [("speaker", "hi", "t1")],
                                       locked_speaker={"interests": ["coffee"]})
    check("the incremental prompt carries the locked-profile block",
          "Locked speaker profile" in append_worker._build_user_message()
          and "coffee" in append_worker._build_user_message())
    plain_worker = BulletPointsWorker([], {}, [("speaker", "hi", "t1")])
    check("no locks leaves the prompt untouched",
          "Locked speaker profile" not in plain_worker._build_user_message())

    speaker.reset()
    check("reset clears the speaker locks",
          speaker.get_speaker_locks() == {} and speaker.locked_speaker() == {},
          f"got {speaker.get_speaker_locks()}")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
