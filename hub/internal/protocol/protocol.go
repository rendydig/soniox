// Package protocol defines the newline-delimited JSON (NDJSON) wire format
// shared by the Python desktop app, the hub, and the worker agents.
//
// One JSON object per line, '\n'-terminated. Every frame is an Envelope; the
// set of populated fields depends on the message type. Payloads are decoded
// with json.Number so a re-encoded frame is byte-comparable to what arrived
// (an int stays 1, it does not become 1.0).
package protocol

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

// MaxLineBytes bounds a single NDJSON frame. Screenshot data URLs ride inside
// payloads, so the limit has to cover a base64 JPEG (a few hundred KB) with
// plenty of headroom.
const MaxLineBytes = 16 << 20

// ErrLineTooLong is returned when a frame exceeds MaxLineBytes.
var ErrLineTooLong = errors.New("protocol: frame exceeds MaxLineBytes")

// Message types (the "type" field).
const (
	TypeHello       = "hello"
	TypeHelloOK     = "hello_ok"
	TypeHelloErr    = "hello_err"
	TypePublish     = "publish"
	TypeSubscribe   = "subscribe"
	TypeUnsubscribe = "unsubscribe"
	TypeEvent       = "event"
	TypeRequest     = "request"
	TypeResponse    = "response"
	TypeResult      = "result"
	TypeResultChunk = "result_chunk"
	TypeAck         = "ack"
	TypeError       = "error"
)

// Handshake roles.
const (
	RolePublisher = "publisher"
	RoleUI        = "ui"
	RoleAgent     = "agent"
	RoleBridge    = "bridge"
)

// Request operations (Envelope.Op).
const (
	OpSnapshot = "snapshot"
	OpRestore  = "restore"
	OpReset    = "reset"
)

// Well-known topics.
const (
	TopicAll              = "*"
	TopicTransPartial     = "transcription.partial"
	TopicTransFinal       = "transcription.final"
	TopicTranslationFinal = "translation.final"
	TopicStatus           = "status"
	TopicError            = "error"
	TopicSessionConfig    = "session.config"
	TopicScreenshotsAdd   = "screenshots.add"
	TopicScreenshotsClear = "screenshots.clear"
	TopicCommand          = "command"
)

// PartialSuffix marks a disposable topic: a frame whose topic ends with it may
// be dropped when a subscriber's queue is saturated. Finals are never dropped.
const PartialSuffix = ".partial"

// Envelope is one wire frame. Unused fields are omitted so the framing stays
// small and readable in logs.
type Envelope struct {
	Type    string         `json:"type"`
	ID      string         `json:"id,omitempty"`
	Ts      float64        `json:"ts,omitempty"`
	Topic   string         `json:"topic,omitempty"`
	Seq     uint64         `json:"seq,omitempty"`
	Role    string         `json:"role,omitempty"`
	Name    string         `json:"name,omitempty"`
	Token   string         `json:"token,omitempty"`
	Topics  []string       `json:"topics,omitempty"`
	Op      string         `json:"op,omitempty"`
	OK      *bool          `json:"ok,omitempty"`
	Error   string         `json:"error,omitempty"`
	JobID   string         `json:"job_id,omitempty"`
	Action  string         `json:"action,omitempty"`
	Text    string         `json:"text,omitempty"`
	Result  any            `json:"result,omitempty"`
	Payload map[string]any `json:"payload,omitempty"`
}

// IsDisposable reports whether a topic's frames may be dropped under
// backpressure (partials only).
func IsDisposable(topic string) bool {
	return strings.HasSuffix(topic, PartialSuffix)
}

// Match reports whether a subscription pattern covers a concrete topic.
// Supported patterns: "*" (everything), a "prefix.*" wildcard, or an exact
// topic name.
func Match(pattern, topic string) bool {
	if pattern == TopicAll || pattern == topic {
		return true
	}
	if strings.HasSuffix(pattern, ".*") {
		return strings.HasPrefix(topic, pattern[:len(pattern)-1])
	}
	return false
}

// Decode parses one frame. Numbers are kept as json.Number so re-encoding does
// not rewrite their representation.
func Decode(line []byte) (*Envelope, error) {
	dec := json.NewDecoder(strings.NewReader(string(line)))
	dec.UseNumber()
	var env Envelope
	if err := dec.Decode(&env); err != nil {
		return nil, fmt.Errorf("protocol: decode: %w", err)
	}
	if env.Type == "" {
		return nil, errors.New("protocol: decode: missing type")
	}
	return &env, nil
}

// Encode marshals a frame and appends the newline terminator.
func Encode(env *Envelope) ([]byte, error) {
	b, err := json.Marshal(env)
	if err != nil {
		return nil, fmt.Errorf("protocol: encode: %w", err)
	}
	return append(b, '\n'), nil
}

// LineReader reads newline-delimited frames, enforcing MaxLineBytes without
// allocating for a whole stream at a time.
type LineReader struct {
	r   *bufio.Reader
	buf []byte
}

// NewLineReader wraps r.
func NewLineReader(r io.Reader) *LineReader {
	return &LineReader{r: bufio.NewReaderSize(r, 64*1024)}
}

// Read returns the next frame, blocking until one is available. It returns
// io.EOF once the stream is closed.
func (lr *LineReader) Read() (*Envelope, error) {
	lr.buf = lr.buf[:0]
	for {
		chunk, err := lr.r.ReadSlice('\n')
		if len(lr.buf)+len(chunk) > MaxLineBytes {
			return nil, ErrLineTooLong
		}
		complete := len(chunk) > 0 && chunk[len(chunk)-1] == '\n'
		if len(chunk) > 0 {
			lr.buf = append(lr.buf, chunk...)
		}
		if complete {
			return Decode(trimEOL(lr.buf))
		}
		if err != nil {
			if err == bufio.ErrBufferFull {
				continue
			}
			if err == io.EOF && len(lr.buf) > 0 {
				// Tolerate a final frame with no trailing newline.
				return Decode(trimEOL(lr.buf))
			}
			return nil, err
		}
	}
}

func trimEOL(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == '\r') {
		b = b[:len(b)-1]
	}
	return b
}
