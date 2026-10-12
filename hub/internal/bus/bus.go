// Package bus fans published topics out to subscribers.
//
// Every subscriber owns an independent queue and a drain goroutine, so a slow
// or stalled reader cannot block the hub or any other subscriber. Backpressure
// is explicit: a saturated queue drops its oldest *disposable* frame (a
// ".partial" topic — those are superseded by the next one anyway) and never
// drops a durable frame. A subscriber that stays saturated past the hard cap is
// evicted, which the server turns into a closed connection — visible, never a
// silent data loss.
package bus

import (
	"errors"
	"sync"

	"soniox-hub/internal/protocol"
)

const (
	// SoftCap is the queue depth at which disposable frames start being
	// dropped (oldest first).
	SoftCap = 256
	// HardCap is the queue depth at which an unread subscriber is evicted.
	HardCap = 4096
	// compactAt bounds the retained backing array between drains.
	compactAt = 4096
)

// ErrEvicted is returned by Push once a subscriber has been evicted.
var ErrEvicted = errors.New("bus: subscriber evicted (queue overflow)")

// Message is one fanned-out frame.
type Message struct {
	Topic      string
	Seq        uint64
	Payload    map[string]any
	Disposable bool
}

type queue struct {
	mu      sync.Mutex
	cond    *sync.Cond
	items   []Message
	head    int
	closed  bool
	evicted bool
}

func newQueue() *queue {
	q := &queue{}
	q.cond = sync.NewCond(&q.mu)
	return q
}

func (q *queue) pending() int { return len(q.items) - q.head }

func (q *queue) push(m Message) error {
	q.mu.Lock()
	defer q.mu.Unlock()
	if q.closed || q.evicted {
		return ErrEvicted
	}
	if q.pending() >= HardCap {
		// Evicted: the connection is about to be closed, so the backlog is
		// worthless. Dropping it makes the drain goroutine stop at once instead
		// of walking thousands of frames nobody will read.
		q.evicted = true
		q.items = q.items[:0]
		q.head = 0
		q.cond.Broadcast()
		return ErrEvicted
	}
	if q.pending() >= SoftCap && m.Disposable {
		// Drop the oldest disposable frame; if the queue holds only durable
		// frames, drop this (newer, and therefore the more disposable) one.
		idx := -1
		for i := q.head; i < len(q.items); i++ {
			if q.items[i].Disposable {
				idx = i
				break
			}
		}
		if idx < 0 {
			return nil
		}
		q.items = append(q.items[:idx], q.items[idx+1:]...)
	}
	q.items = append(q.items, m)
	q.cond.Signal()
	return nil
}

// pop blocks until a frame is available. ok is false once the queue is closed
// or evicted and drained.
func (q *queue) pop() (Message, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	for q.pending() == 0 && !q.closed && !q.evicted {
		q.cond.Wait()
	}
	if q.pending() == 0 {
		return Message{}, false
	}
	m := q.items[q.head]
	q.items[q.head] = Message{}
	q.head++
	switch {
	case q.pending() == 0:
		// Fully drained: recycle the array under the next appends.
		q.items = q.items[:0]
		q.head = 0
	case q.head >= compactAt:
		q.items = append(q.items[:0], q.items[q.head:]...)
		q.head = 0
	}
	return m, true
}

// close wakes the drain goroutine; pending frames are still delivered (a
// subscriber that disconnects cleanly gets the finals already queued for it).
// Eviction, by contrast, discards the backlog: see push.
func (q *queue) close() {
	q.mu.Lock()
	q.closed = true
	q.cond.Broadcast()
	q.mu.Unlock()
}

// evictedErr reports whether the queue was evicted.
func (q *queue) evictedErr() bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.evicted
}

// Subscriber is one connected consumer with its own queue.
type Subscriber struct {
	ID       uint64
	Name     string
	queue    *queue
	patterns map[string]struct{}

	bus *Bus
	mu  sync.Mutex
}

// Matches reports whether the subscriber asked for this topic.
func (s *Subscriber) Matches(topic string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for p := range s.patterns {
		if protocol.Match(p, topic) {
			return true
		}
	}
	return false
}

// AddTopics extends the subscription set.
func (s *Subscriber) AddTopics(topics []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, t := range topics {
		if t != "" {
			s.patterns[t] = struct{}{}
		}
	}
}

// RemoveTopics narrows the subscription set.
func (s *Subscriber) RemoveTopics(topics []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, t := range topics {
		delete(s.patterns, t)
	}
}

// Pop blocks for the next fanned-out frame. ok is false when the subscriber is
// closed or evicted.
func (s *Subscriber) Pop() (Message, bool) { return s.queue.pop() }

// Evicted reports whether the subscriber was dropped for being too slow.
func (s *Subscriber) Evicted() bool { return s.queue.evictedErr() }

// Close detaches the subscriber. The bus forgets it immediately; frames already
// queued are still delivered before Pop reports false.
func (s *Subscriber) Close() {
	s.bus.remove(s)
	s.queue.close()
}

// Bus is the topic registry.
type Bus struct {
	mu     sync.RWMutex
	subs   map[uint64]*Subscriber
	nextID uint64
	seqs   map[string]uint64
}

// New returns an empty bus.
func New() *Bus {
	return &Bus{subs: map[uint64]*Subscriber{}, seqs: map[string]uint64{}}
}

// Subscribe registers a new subscriber for the given patterns.
func (b *Bus) Subscribe(name string, topics []string) *Subscriber {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.nextID++
	s := &Subscriber{
		ID:       b.nextID,
		Name:     name,
		queue:    newQueue(),
		patterns: map[string]struct{}{},
		bus:      b,
	}
	s.AddTopics(topics)
	b.subs[s.ID] = s
	return s
}

func (b *Bus) remove(s *Subscriber) {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.subs, s.ID)
}

// Subscribers returns how many subscribers are currently attached.
func (b *Bus) Subscribers() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.subs)
}

// Publish assigns the topic's next sequence number and fans the frame out.
// It returns the sequence number and how many subscribers were dropped for
// being too slow (their connections should be closed by the caller).
func (b *Bus) Publish(topic string, payload map[string]any) (uint64, []*Subscriber) {
	if payload == nil {
		payload = map[string]any{}
	}
	msg := Message{
		Topic:      topic,
		Payload:    payload,
		Disposable: protocol.IsDisposable(topic),
	}

	b.mu.Lock()
	b.seqs[topic]++
	msg.Seq = b.seqs[topic]
	targets := make([]*Subscriber, 0, len(b.subs))
	for _, s := range b.subs {
		if s.Matches(topic) {
			targets = append(targets, s)
		}
	}
	b.mu.Unlock()

	var dropped []*Subscriber
	for _, s := range targets {
		if err := s.queue.push(msg); err != nil {
			dropped = append(dropped, s)
		}
	}
	return msg.Seq, dropped
}

// Seq returns the last sequence number issued for a topic.
func (b *Bus) Seq(topic string) uint64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.seqs[topic]
}
