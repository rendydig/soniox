// Package persist durably records what the hub sees.
//
// Two artefacts, both crash-friendly:
//   - an append-only JSONL event log (every published topic, one line each) for
//     after-the-fact debugging;
//   - a debounced full-state snapshot, written atomically via a temp file +
//     rename, shaped like sessions/current.json.
//
// Long string values (screenshot data URLs) are elided in the event log so a
// session's log stays readable.
package persist

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// MaxValueBytes bounds a single string value in the event log.
const MaxValueBytes = 512

// Options configure a Writer. Empty paths disable that artefact.
type Options struct {
	EventsPath   string
	SnapshotPath string
	// Debounce coalesces a burst of changes into one snapshot write.
	Debounce time.Duration
	// Snapshot supplies the current state to serialize.
	Snapshot func() any
	// Logf receives non-fatal errors (nil = silent).
	Logf func(format string, args ...any)
}

// Writer appends events and writes snapshots.
type Writer struct {
	opts Options

	mu     sync.Mutex
	events *os.File

	snapMu   sync.Mutex
	dirty    chan struct{}
	stop     chan struct{}
	done     chan struct{}
	stopOnce sync.Once
}

// New creates the writer and starts its snapshot goroutine.
func New(opts Options) (*Writer, error) {
	if opts.Debounce <= 0 {
		opts.Debounce = 2 * time.Second
	}
	w := &Writer{
		opts:  opts,
		dirty: make(chan struct{}, 1),
		stop:  make(chan struct{}),
		done:  make(chan struct{}),
	}
	if opts.EventsPath != "" {
		if err := os.MkdirAll(filepath.Dir(opts.EventsPath), 0o755); err != nil {
			return nil, err
		}
		f, err := os.OpenFile(opts.EventsPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			return nil, err
		}
		w.events = f
	}
	go w.snapshotLoop()
	return w, nil
}

// AppendEvent writes one JSONL line. Errors are reported through Logf and
// never propagate: persistence must not break the hub's message path.
func (w *Writer) AppendEvent(topic string, seq uint64, payload map[string]any) {
	if w.events == nil {
		return
	}
	line, err := json.Marshal(map[string]any{
		"ts":      time.Now().Format("2006-01-02T15:04:05.000000"),
		"seq":     seq,
		"topic":   topic,
		"payload": elide(payload),
	})
	if err != nil {
		w.logf("persist: encode event: %v", err)
		return
	}
	w.mu.Lock()
	_, err = w.events.Write(append(line, '\n'))
	w.mu.Unlock()
	if err != nil {
		w.logf("persist: write event: %v", err)
	}
}

// MarkDirty schedules a snapshot write.
func (w *Writer) MarkDirty() {
	if w.opts.SnapshotPath == "" || w.opts.Snapshot == nil {
		return
	}
	select {
	case w.dirty <- struct{}{}:
	default:
	}
}

// Flush writes a snapshot immediately.
func (w *Writer) Flush() error {
	if w.opts.SnapshotPath == "" || w.opts.Snapshot == nil {
		return nil
	}
	state := w.opts.Snapshot()
	b, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("persist: encode snapshot: %w", err)
	}
	w.snapMu.Lock()
	defer w.snapMu.Unlock()
	if err := os.MkdirAll(filepath.Dir(w.opts.SnapshotPath), 0o755); err != nil {
		return err
	}
	tmp := w.opts.SnapshotPath + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, w.opts.SnapshotPath)
}

// Archive writes a state blob to dir/<id>.json and returns the path.
func (w *Writer) Archive(dir string, id string, state any) (string, error) {
	b, err := json.Marshal(state)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	if id == "" {
		id = time.Now().Format("20060102-150405")
	}
	path := filepath.Join(dir, id+".json")
	return path, os.WriteFile(path, b, 0o644)
}

// Close flushes and stops the writer.
func (w *Writer) Close() {
	w.stopOnce.Do(func() { close(w.stop) })
	select {
	case <-w.done:
	case <-time.After(2 * time.Second):
	}
	_ = w.Flush()
	w.mu.Lock()
	if w.events != nil {
		_ = w.events.Close()
		w.events = nil
	}
	w.mu.Unlock()
}

func (w *Writer) snapshotLoop() {
	defer close(w.done)
	var timer *time.Timer
	var deadline <-chan time.Time
	for {
		select {
		case <-w.stop:
			return
		case <-deadline:
			if err := w.Flush(); err != nil {
				w.logf("persist: snapshot: %v", err)
			}
			timer, deadline = nil, nil
		case <-w.dirty:
			if timer != nil {
				timer.Stop()
			}
			timer = time.NewTimer(w.opts.Debounce)
			deadline = timer.C
		}
	}
}

func (w *Writer) logf(format string, args ...any) {
	if w.opts.Logf != nil {
		w.opts.Logf(format, args...)
	}
}

// elide replaces oversized string values with a size marker.
func elide(payload map[string]any) map[string]any {
	if payload == nil {
		return nil
	}
	out := make(map[string]any, len(payload))
	for k, v := range payload {
		if s, ok := v.(string); ok && len(s) > MaxValueBytes {
			out[k] = fmt.Sprintf("<%d bytes elided>", len(s))
			continue
		}
		out[k] = v
	}
	return out
}
