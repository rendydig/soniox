package store

import (
	"encoding/json"
	"testing"

	"soniox-hub/internal/protocol"
)

func TestFinalTranscriptionDerivesConversationTurn(t *testing.T) {
	s := New()
	changed := s.Apply(protocol.TopicTransFinal, map[string]any{
		"source": "speaker", "text": "hello there", "endpoint": true,
		"timestamp": "2026-10-12T06:00:00.000000",
	})
	if !changed {
		t.Fatal("a non-empty final should change the state")
	}
	snap := s.Snapshot()
	if len(snap.Transcriptions) != 1 {
		t.Fatalf("transcriptions=%d", len(snap.Transcriptions))
	}
	if snap.Transcriptions[0].Timestamp != "2026-10-12T06:00:00.000000" {
		t.Fatalf("publisher timestamp not honored: %q", snap.Transcriptions[0].Timestamp)
	}
	if len(snap.Conversation) != 1 {
		t.Fatalf("conversation=%d", len(snap.Conversation))
	}
	turn := snap.Conversation[0]
	if turn.Text != "hello there" || turn.Role != "speaker" || turn.Suggestion != "" {
		t.Fatalf("unexpected turn: %+v", turn)
	}
}

func TestPartialAndEmptyFinalsAreIgnored(t *testing.T) {
	s := New()
	if s.Apply(protocol.TopicTransPartial, map[string]any{"text": "hel"}) {
		t.Fatal("partials must not touch the session state")
	}
	if s.Apply(protocol.TopicTransFinal, map[string]any{"source": "host", "text": "   "}) {
		t.Fatal("blank finals must not be stored")
	}
	if len(s.Snapshot().Transcriptions) != 0 {
		t.Fatal("state changed")
	}
}

// Snapshot hands out copies: a caller mutating what it got must not be able to
// corrupt the live state (the Python SessionStore discipline this mirrors).
func TestSnapshotIsACopy(t *testing.T) {
	s := New()
	s.Apply(protocol.TopicTransFinal, map[string]any{"source": "host", "text": "one"})
	s.SetBullets([]any{map[string]any{"text": "b1"}})
	s.SetSpeaker(map[string]any{"name": "Ada"})
	s.Apply(protocol.TopicBullets, map[string]any{
		"items":   []any{map[string]any{"text": "b1"}},
		"speaker": map[string]any{"name": "Ada"},
		"windows": []any{map[string]any{"mode": "auto", "from_index": 0, "to_index": 0}},
	})

	snap := s.Snapshot()
	snap.Transcriptions[0].Text = "MUTATED"
	snap.Conversation[0].Text = "MUTATED"
	snap.Bullets[0].(map[string]any)["text"] = "MUTATED"
	snap.BulletWindows[0]["mode"] = "MUTATED"
	snap.Speaker["name"] = "MUTATED"
	snap.Translations = append(snap.Translations, Line{Text: "injected"})

	fresh := s.Snapshot()
	if fresh.Transcriptions[0].Text != "one" {
		t.Fatalf("transcription mutated through the snapshot: %+v", fresh.Transcriptions)
	}
	if fresh.Conversation[0].Text != "one" {
		t.Fatalf("conversation mutated through the snapshot: %+v", fresh.Conversation)
	}
	if fresh.Bullets[0].(map[string]any)["text"] != "b1" {
		t.Fatalf("bullets mutated through the snapshot: %+v", fresh.Bullets)
	}
	if fresh.BulletWindows[0]["mode"] != "auto" {
		t.Fatalf("bullet windows mutated through the snapshot: %+v", fresh.BulletWindows)
	}
	if fresh.Speaker["name"] != "Ada" {
		t.Fatalf("speaker mutated through the snapshot: %+v", fresh.Speaker)
	}
	if len(fresh.Translations) != 0 {
		t.Fatalf("translations mutated through the snapshot: %+v", fresh.Translations)
	}
}

// Bullet locks round-trip through Apply/Snapshot and survive a restore.
func TestBulletLocksRoundTrip(t *testing.T) {
	s := New()
	s.Apply(protocol.TopicBullets, map[string]any{
		"items": []any{"b1", "b2", "b3"},
		"locks": []any{true, false, true},
	})
	locks := s.BulletLocks()
	if len(locks) != 3 || locks[0] != true || locks[1] != false || locks[2] != true {
		t.Fatalf("locks not stored: %+v", locks)
	}
	// A caller mutating the getter's slice must not touch the live state.
	locks[0] = false
	if s.BulletLocks()[0] != true {
		t.Fatal("locks mutated through the getter")
	}
	// Restore seeds them from a persisted snapshot.
	raw := map[string]any{
		"bullets":      []any{"b1"},
		"bullet_locks": []any{true},
	}
	if err := s.Restore(raw); err != nil {
		t.Fatal(err)
	}
	if got := s.Snapshot().BulletLocks; len(got) != 1 || got[0] != true {
		t.Fatalf("locks not restored: %+v", got)
	}
}

// Bullets are append-only: the store must not truncate them (there is no cap).
func TestBulletsAreNotCapped(t *testing.T) {
	s := New()
	items := make([]any, 0, 80)
	for i := 0; i < 80; i++ {
		items = append(items, map[string]any{"text": "point"})
	}
	s.Apply(protocol.TopicBullets, map[string]any{"items": items})
	s.Apply(protocol.TopicBullets, map[string]any{
		"windows": []any{map[string]any{"mode": "auto", "from_index": 0, "to_index": 79}},
	})
	snap := s.Snapshot()
	if len(snap.Bullets) != 80 {
		t.Fatalf("bullets were truncated: %d", len(snap.Bullets))
	}
	if len(snap.BulletWindows) != 1 {
		t.Fatalf("bullet_windows=%d want 1", len(snap.BulletWindows))
	}
}

func TestCapsAreEnforced(t *testing.T) {
	s := New()
	for i := 0; i < CapTranscriptions+50; i++ {
		s.Apply(protocol.TopicTransFinal, map[string]any{"source": "host", "text": "line"})
	}
	snap := s.Snapshot()
	if len(snap.Transcriptions) != CapTranscriptions {
		t.Fatalf("transcriptions=%d want %d", len(snap.Transcriptions), CapTranscriptions)
	}
	if len(snap.Conversation) != CapConversation {
		t.Fatalf("conversation=%d want %d", len(snap.Conversation), CapConversation)
	}
}

func TestScreenshotsCapAndClear(t *testing.T) {
	s := New()
	for i := 0; i < CapScreenshots+5; i++ {
		s.Apply(protocol.TopicScreenshotsAdd, map[string]any{"data_url": "data:image/jpeg;base64,AAAA"})
	}
	if got := len(s.Snapshot().Screenshots); got != CapScreenshots {
		t.Fatalf("screenshots=%d want %d", got, CapScreenshots)
	}
	s.Apply(protocol.TopicScreenshotsClear, nil)
	if got := len(s.Snapshot().Screenshots); got != 0 {
		t.Fatalf("screenshots not cleared: %d", got)
	}
}

func TestSessionConfigIsKept(t *testing.T) {
	s := New()
	s.Apply(protocol.TopicSessionConfig, map[string]any{"auto_reply_enabled": true, "purpose": "language_learning"})
	cfg := s.Config()
	if cfg["auto_reply_enabled"] != true || cfg["purpose"] != "language_learning" {
		t.Fatalf("config not stored: %+v", cfg)
	}
	// A caller mutating the returned map must not affect the store.
	cfg["purpose"] = "MUTATED"
	if s.Config()["purpose"] != "language_learning" {
		t.Fatal("config mutated through the getter")
	}
}

func TestResetKeepsConfigAndClearsSession(t *testing.T) {
	s := New()
	s.Apply(protocol.TopicSessionConfig, map[string]any{"auto_reply_enabled": true})
	s.Apply(protocol.TopicTransFinal, map[string]any{"source": "host", "text": "hi"})
	s.SetBullets([]any{"b"})
	s.Apply(protocol.TopicBullets, map[string]any{
		"items":   []any{"b"},
		"windows": []any{map[string]any{"mode": "auto", "from_index": 0, "to_index": 0}},
	})
	s.SetLastPickup("picked")

	s.Reset()

	snap := s.Snapshot()
	if len(snap.Transcriptions) != 0 || len(snap.Conversation) != 0 || len(snap.Bullets) != 0 {
		t.Fatalf("reset left state behind: %+v", snap)
	}
	if len(snap.BulletWindows) != 0 {
		t.Fatalf("reset left bullet windows behind: %+v", snap.BulletWindows)
	}
	if snap.LastPickup != "" {
		t.Fatalf("last_pickup not cleared: %q", snap.LastPickup)
	}
	if s.Config()["auto_reply_enabled"] != true {
		t.Fatal("reset must keep the live session config")
	}
}

func TestRestoreSeedsEveryField(t *testing.T) {
	s := New()
	raw := map[string]any{
		"id":             "20261012-060000",
		"created_at":     "2026-10-12T06:00:00.000000",
		"bullets":        []any{map[string]any{"text": "bullet"}},
		"bullet_windows": []any{map[string]any{"mode": "auto", "from_index": 0, "to_index": 0}},
		"conversation":   []any{map[string]any{"text": "hi", "role": "speaker", "suggestion": ""}},
		"transcriptions": []any{map[string]any{"source": "host", "text": "hi", "timestamp": "t"}},
		"translations":   []any{map[string]any{"source": "host", "text": "hai", "timestamp": "t"}},
		"aireply_results": []any{map[string]any{"text": "reply"}},
		"screenshots":    []any{"data:image/jpeg;base64,AAAA"},
		"last_pickup":    "something",
		"speaker":        map[string]any{"name": "Ada"},
	}
	if err := s.Restore(raw); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	snap := s.Snapshot()
	if snap.ID != "20261012-060000" {
		t.Fatalf("id=%q", snap.ID)
	}
	if len(snap.Transcriptions) != 1 || snap.Transcriptions[0].Text != "hi" {
		t.Fatalf("transcriptions=%+v", snap.Transcriptions)
	}
	if len(snap.Translations) != 1 || snap.Translations[0].Text != "hai" {
		t.Fatalf("translations=%+v", snap.Translations)
	}
	if len(snap.Conversation) != 1 {
		t.Fatalf("conversation=%+v", snap.Conversation)
	}
	if len(snap.Bullets) != 1 || len(snap.GeminiResults) != 1 || len(snap.Screenshots) != 1 {
		t.Fatalf("restore incomplete: %+v", snap)
	}
	if len(snap.BulletWindows) != 1 || snap.BulletWindows[0]["mode"] != "auto" {
		t.Fatalf("bullet windows not restored: %+v", snap.BulletWindows)
	}
	if snap.LastPickup != "something" || snap.Speaker["name"] != "Ada" {
		t.Fatalf("scalars not restored: %+v", snap)
	}
}

// A restored session must keep only the newest Cap entries.
func TestRestoreTrimsToCaps(t *testing.T) {
	s := New()
	lines := make([]any, 0, CapTranscriptions+10)
	for i := 0; i < CapTranscriptions+10; i++ {
		lines = append(lines, map[string]any{"source": "host", "text": "x", "timestamp": "t"})
	}
	if err := s.Restore(map[string]any{"transcriptions": lines}); err != nil {
		t.Fatal(err)
	}
	if got := len(s.Snapshot().Transcriptions); got != CapTranscriptions {
		t.Fatalf("restored %d lines, want %d", got, CapTranscriptions)
	}
}

// The snapshot's JSON shape is what sessions/current.json looks like, so it can
// be archived verbatim.
func TestSnapshotJSONShape(t *testing.T) {
	s := New()
	s.Apply(protocol.TopicTransFinal, map[string]any{"source": "host", "text": "hi"})
	b, err := json.Marshal(s.Snapshot())
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{
		"id", "created_at", "updated_at", "bullets", "bullet_windows", "bullet_locks",
		"conversation", "transcriptions", "translations", "aireply_results", "screenshots",
		"last_pickup", "speaker",
	} {
		if _, ok := m[key]; !ok {
			t.Errorf("snapshot is missing %q", key)
		}
	}
	for _, key := range []string{"Config", "Purposes", "Status"} {
		if _, ok := m[key]; ok {
			t.Errorf("transient field %q must not be persisted", key)
		}
	}
}
