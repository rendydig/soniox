import json
import os
import tempfile
import time

from src.session_store import SessionStore

d = tempfile.mkdtemp()
path = os.path.join(d, "current.json")

s = SessionStore(d)
# append + cap
s.append("transcriptions", {"text": "a"}, cap=2)
s.append("transcriptions", {"text": "b"}, cap=2)
s.append("transcriptions", {"text": "c"}, cap=2)
assert [t["text"] for t in s.snapshot()["transcriptions"]] == ["b", "c"]
s.update("bullets", ["x", "y"])
s.flush()
assert os.path.exists(path)
with open(path, encoding="utf-8") as f:
    data = json.load(f)
assert data["bullets"] == ["x", "y"], data["bullets"]
assert [t["text"] for t in data["transcriptions"]] == ["b", "c"]

# bullet_locks round-trips (normalized to booleans) and rides in current.json
s.set_bullet_locks([1, 0, None, "x"])
s.flush()
with open(path, encoding="utf-8") as f:
    data = json.load(f)
assert data["bullet_locks"] == [True, False, False, True], data["bullet_locks"]
assert s.snapshot()["bullet_locks"] == [True, False, False, True]

# speaker_locks round-trips (coerced) and rides in current.json, aligned to the
# speaker profile's shape so a stale/short list cannot mis-pin an item.
s.set_speaker({"name": "Maya", "interests": ["coffee", "running"],
               "goals": [], "pain_points": [], "facts": [], "location": "", "occupation": ""})
s.set_speaker_locks({"name": True, "interests": [True, 0], "goals": []})
s.flush()
with open(path, encoding="utf-8") as f:
    data = json.load(f)
assert data["speaker_locks"]["name"] is True, data["speaker_locks"]
assert data["speaker_locks"]["interests"] == [True, False], data["speaker_locks"]
assert data["speaker_locks"]["occupation"] is False, data["speaker_locks"]

# A short/absent lock list pads to the profile (the older-session case).
with open(path, "w", encoding="utf-8") as f:
    json.dump({"id": "legacy-locks", "speaker": {"interests": ["a", "b", "c"]},
               "speaker_locks": {"interests": [True]}}, f)
s_locks = SessionStore(d)
assert s_locks.snapshot()["speaker_locks"]["interests"] == [True, False, False], \
    s_locks.snapshot()["speaker_locks"]
assert s_locks.snapshot()["speaker_locks"]["name"] is False
s_locks.close()

# async debounced write
s.append("gemini_results", {"text": "g", "mode": "manual"})
time.sleep(3)
with open(path, encoding="utf-8") as f:
    data = json.load(f)
assert any(g["text"] == "g" for g in data["gemini_results"]), data["gemini_results"]

# new_session archives + resets
archived = s.new_session()
assert archived and os.path.exists(archived), archived
assert s.snapshot()["bullets"] == []
assert s.snapshot()["transcriptions"] == []
assert s.snapshot()["bullet_locks"] == []
with open(path, encoding="utf-8") as f:
    data = json.load(f)
assert data["bullets"] == [] and data["transcriptions"] == []
assert data["bullet_locks"] == []
s.close()

# round-trip load + corrupt fallback
s2 = SessionStore(d)
s2.update("bullets", ["p"])
s2.flush()
s2.close()
s3 = SessionStore(d)
assert s3.snapshot()["bullets"] == ["p"], s3.snapshot()["bullets"]
s3.close()

# an older session file (no bullet_locks) normalizes to []
with open(path, "w", encoding="utf-8") as f:
    json.dump({"bullets": ["q"], "id": "legacy"}, f)
s_legacy = SessionStore(d)
assert s_legacy.snapshot()["bullet_locks"] == [], s_legacy.snapshot()["bullet_locks"]
assert s_legacy.snapshot()["bullets"] == ["q"]
s_legacy.close()

with open(path, "w", encoding="utf-8") as f:
    f.write("{not json")
s4 = SessionStore(d)
assert s4.snapshot()["bullets"] == []
assert s4.snapshot()["id"]
s4.close()

print("STORE_OK")
