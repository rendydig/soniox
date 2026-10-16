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

    venv/bin/python _tmp_bullet_delta_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from src.bullet_points_worker import BulletPointsWorker  # noqa: E402
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

    def fake_start_worker(current_bullets, current_speaker, lines, rebuild=False):
        controller._fake_calls.append(
            {"bullets": list(current_bullets), "lines": list(lines), "rebuild": rebuild}
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

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
