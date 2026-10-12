package store

import (
	"encoding/json"
	"strings"
	"sync"
	"time"

	"soniox-hub/internal/protocol"
)

// Retention caps. These mirror src/session_store.py's SESSION_CAPS and
// src/controllers/translation_controller.py's MAX_HISTORY_TURNS. Bullets and
// their windows are deliberately uncapped (append-only, one point per update):
// every other list is bounded by construction, those two grow with the session.
const (
	CapTranscriptions = 500
	CapTranslations   = 500
	CapConversation   = 25
	CapGeminiResults  = 100
	CapScreenshots    = 20
)

// pyTimeLayout matches Python's datetime.now().isoformat(): local time, no
// timezone, microsecond precision.
const pyTimeLayout = "2006-01-02T15:04:05.000000"

// Line is one labeled transcription/translation entry ("[SOURCE] text").
type Line struct {
	Source    string `json:"source"`
	Text      string `json:"text"`
	Timestamp string `json:"timestamp"`
}

// Turn is one conversation-history entry consumed by the auto-reply worker.
type Turn struct {
	Text       string `json:"text"`
	Role       string `json:"role"`
	Suggestion string `json:"suggestion"`
}

// State is the whole live session. Its JSON shape matches
// sessions/current.json so it can be archived verbatim.
type State struct {
	ID             string           `json:"id"`
	CreatedAt      string           `json:"created_at"`
	UpdatedAt      string           `json:"updated_at"`
	Bullets        []any            `json:"bullets"`
	BulletWindows  []map[string]any `json:"bullet_windows"`
	Conversation   []Turn           `json:"conversation"`
	Transcriptions []Line           `json:"transcriptions"`
	Translations   []Line           `json:"translations"`
	GeminiResults  []map[string]any `json:"gemini_results"`
	Screenshots    []string         `json:"screenshots"`
	LastPickup     string           `json:"last_pickup"`
	Speaker        map[string]any   `json:"speaker"`

	// Transient (never persisted): replayed to a (re)connecting UI so a
	// reloaded pane sees the current settings/purposes without a round trip.
	Config   map[string]any `json:"-"`
	Purposes map[string]any `json:"-"`
	Status   string         `json:"-"`
}

// Store is the single source of truth. All mutation goes through Apply or an
// explicit setter; Snapshot hands out copies.
type Store struct {
	mu sync.RWMutex

	transcriptions *Ring[Line]
	translations   *Ring[Line]
	conversation   *Ring[Turn]
	geminiResults  *Ring[map[string]any]
	screenshots    *Ring[string]

	id        string
	createdAt string
	updatedAt string

	bullets       []any
	bulletWindows []map[string]any
	speaker       map[string]any
	lastPickup    string
	config     map[string]any
	purposes   map[string]any
	status     string
}

// New returns a store seeded with an empty session.
func New() *Store {
	s := &Store{
		transcriptions: NewRing[Line](CapTranscriptions),
		translations:   NewRing[Line](CapTranslations),
		conversation:   NewRing[Turn](CapConversation),
		geminiResults:  NewRing[map[string]any](CapGeminiResults),
		screenshots:    NewRing[string](CapScreenshots),
	}
	s.resetLocked()
	return s
}

// --- mutation ---------------------------------------------------------------

// Apply routes one published topic into the state. Topics the hub does not own
// are ignored (they are still fanned out to subscribers by the bus).
func (s *Store) Apply(topic string, payload map[string]any) (changed bool) {
	switch topic {
	case protocol.TopicTransFinal:
		source := str(payload, "source")
		text := str(payload, "text")
		if strings.TrimSpace(text) == "" {
			return false
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		s.transcriptions.Push(Line{Source: source, Text: text, Timestamp: ts(payload)})
		s.conversation.Push(Turn{Text: text, Role: source, Suggestion: ""})
		s.touchLocked()
		return true

	case protocol.TopicTranslationFinal:
		text := str(payload, "text")
		if strings.TrimSpace(text) == "" {
			return false
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		s.translations.Push(Line{Source: str(payload, "source"), Text: text, Timestamp: ts(payload)})
		s.touchLocked()
		return true

	case protocol.TopicSessionConfig:
		s.mu.Lock()
		defer s.mu.Unlock()
		s.config = cloneMap(payload)
		return false

	case protocol.TopicScreenshotsAdd:
		data := str(payload, "data_url")
		if data == "" {
			return false
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		s.screenshots.Push(data)
		s.touchLocked()
		return true

	case protocol.TopicScreenshotsClear:
		s.mu.Lock()
		defer s.mu.Unlock()
		s.screenshots.Clear()
		s.touchLocked()
		return true

	case protocol.TopicBullets:
		s.mu.Lock()
		defer s.mu.Unlock()
		if raw, ok := payload["items"]; ok {
			s.setBulletsLocked(toAnySlice(raw))
		}
		if raw, ok := payload["speaker"]; ok {
			s.speaker = cloneMap(toMap(raw))
		}
		if raw, ok := payload["windows"]; ok {
			s.bulletWindows = toMapSlice(raw)
		}
		s.touchLocked()
		return true

	case protocol.TopicStatus, protocol.TopicError:
		s.mu.Lock()
		defer s.mu.Unlock()
		s.status = str(payload, "message")
		return false

	case topicPurposes:
		s.mu.Lock()
		defer s.mu.Unlock()
		s.purposes = cloneMap(payload)
		return false
	}
	return false
}

// topicPurposes mirrors the browser-bound purpose_state frame.
const topicPurposes = "purpose_state"

// setBulletsLocked replaces the bullet list (uncapped: append-only by design).
func (s *Store) setBulletsLocked(bullets []any) {
	s.bullets = cloneSlice(bullets)
}

// SetBullets replaces the bullet list.
func (s *Store) SetBullets(bullets []any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.setBulletsLocked(bullets)
	s.touchLocked()
}

// SetSpeaker replaces the KYC speaker profile.
func (s *Store) SetSpeaker(profile map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.speaker = cloneMap(profile)
	s.touchLocked()
}

// SetLastPickup replaces the "Last Picked Up" text.
func (s *Store) SetLastPickup(text string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.lastPickup = text
	s.touchLocked()
}

// AppendGeminiResult records one finalized AI reply.
func (s *Store) AppendGeminiResult(result map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.geminiResults.Push(cloneMap(result))
	s.touchLocked()
}

// SetPurposes records the latest purpose_state frame for UI replay.
func (s *Store) SetPurposes(payload map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purposes = cloneMap(payload)
}

// Reset starts a fresh session. The live config and the purpose registry
// survive: both are application-level, not session-level (AI-learned personas
// are global, exactly as the purpose store treats them today).
func (s *Store) Reset() {
	s.mu.Lock()
	defer s.mu.Unlock()
	config, purposes := s.config, s.purposes
	s.resetLocked()
	s.config, s.purposes = config, purposes
}

// Restore replaces the session from a persisted snapshot (op=restore).
func (s *Store) Restore(raw map[string]any) error {
	b, err := json.Marshal(raw)
	if err != nil {
		return err
	}
	var in State
	if err := json.Unmarshal(b, &in); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	config, purposes := s.config, s.purposes
	s.resetLocked()
	s.config, s.purposes = config, purposes
	s.id = in.ID
	s.createdAt = in.CreatedAt
	s.transcriptions.Set(in.Transcriptions)
	s.translations.Set(in.Translations)
	s.conversation.Set(in.Conversation)
	s.geminiResults.Set(in.GeminiResults)
	s.screenshots.Set(in.Screenshots)
	if in.Bullets != nil {
		s.bullets = cloneSlice(in.Bullets)
	}
	if in.BulletWindows != nil {
		s.bulletWindows = cloneMapSlice(in.BulletWindows)
	}
	if in.Speaker != nil {
		s.speaker = cloneMap(in.Speaker)
	}
	s.lastPickup = in.LastPickup
	return nil
}

// --- reads ------------------------------------------------------------------

// Snapshot returns a deep copy of the live state.
func (s *Store) Snapshot() State {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return State{
		ID:             s.id,
		CreatedAt:      s.createdAt,
		UpdatedAt:      s.updatedAt,
		Bullets:        cloneSlice(s.bullets),
		BulletWindows:  cloneMapSlice(s.bulletWindows),
		Conversation:   s.conversation.Slice(),
		Transcriptions: s.transcriptions.Slice(),
		Translations:   s.translations.Slice(),
		GeminiResults:  s.geminiResults.Slice(),
		Screenshots:    s.screenshots.Slice(),
		LastPickup:     s.lastPickup,
		Speaker:        cloneMap(s.speaker),
		Config:         cloneMap(s.config),
		Purposes:       cloneMap(s.purposes),
		Status:         s.status,
	}
}

// Conversation returns the recent conversation turns (newest last).
func (s *Store) Conversation() []Turn {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.conversation.Slice()
}

// Bullets returns the current bullet list.
func (s *Store) Bullets() []any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return cloneSlice(s.bullets)
}

// BulletWindows returns the per-update provenance of the bullet list.
func (s *Store) BulletWindows() []map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return cloneMapSlice(s.bulletWindows)
}

// Speaker returns the current speaker profile.
func (s *Store) Speaker() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return cloneMap(s.speaker)
}

// Config returns the latest session.config payload.
func (s *Store) Config() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return cloneMap(s.config)
}

// LastPickup returns the current "Last Picked Up" text.
func (s *Store) LastPickup() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.lastPickup
}

// --- internals --------------------------------------------------------------

func (s *Store) resetLocked() {
	now := time.Now()
	s.id = now.Format("20060102-150405")
	s.createdAt = now.Format(pyTimeLayout)
	s.updatedAt = s.createdAt
	s.transcriptions.Clear()
	s.translations.Clear()
	s.conversation.Clear()
	s.geminiResults.Clear()
	s.screenshots.Clear()
	s.bullets = []any{}
	s.bulletWindows = []map[string]any{}
	s.speaker = map[string]any{}
	s.lastPickup = ""
	s.status = ""
}

func (s *Store) touchLocked() {
	s.updatedAt = time.Now().Format(pyTimeLayout)
}

func str(payload map[string]any, key string) string {
	if payload == nil {
		return ""
	}
	v, ok := payload[key]
	if !ok || v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// ts uses the publisher-supplied timestamp when present (the Python side keeps
// producing the exact same datetime.now().isoformat() string it always has),
// falling back to a freshly generated one.
func ts(payload map[string]any) string {
	if t := str(payload, "timestamp"); t != "" {
		return t
	}
	return time.Now().Format(pyTimeLayout)
}

// cloneMap defensively copies a payload. Values nest (a bullet is a map, a
// profile's lists hold maps), so the copy descends into maps and slices and
// leaves scalars alone. The cost is negligible at these sizes and it means no
// caller can ever mutate live hub state by accident.
func cloneMap(in map[string]any) map[string]any {
	if in == nil {
		return map[string]any{}
	}
	out := make(map[string]any, len(in))
	for k, v := range in {
		out[k] = cloneAny(v)
	}
	return out
}

func cloneAny(v any) any {
	switch t := v.(type) {
	case map[string]any:
		return cloneMap(t)
	case []any:
		out := make([]any, len(t))
		for i, item := range t {
			out[i] = cloneAny(item)
		}
		return out
	default:
		return v
	}
}

// cloneSlice copies a slice of arbitrary values element-wise.
func cloneSlice(in []any) []any {
	if in == nil {
		return []any{}
	}
	out := make([]any, len(in))
	for i, item := range in {
		out[i] = cloneAny(item)
	}
	return out
}

// cloneMapSlice copies a slice of maps element-wise (deep).
func cloneMapSlice(in []map[string]any) []map[string]any {
	if in == nil {
		return []map[string]any{}
	}
	out := make([]map[string]any, len(in))
	for i, item := range in {
		out[i] = cloneMap(item)
	}
	return out
}

// toAnySlice coerces a decoded payload value to a slice, dropping non-slices.
func toAnySlice(v any) []any {
	items, _ := v.([]any)
	return items
}

// toMap coerces a decoded payload value to a map.
func toMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

// toMapSlice keeps the map entries of a decoded slice, cloning each one.
func toMapSlice(v any) []map[string]any {
	items, _ := v.([]any)
	out := make([]map[string]any, 0, len(items))
	for _, item := range items {
		if m, ok := item.(map[string]any); ok {
			out = append(out, cloneMap(m))
		}
	}
	return out
}
