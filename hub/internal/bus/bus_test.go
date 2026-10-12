package bus

import (
	"errors"
	"testing"
	"time"

	"soniox-hub/internal/protocol"
)

func drain(t *testing.T, s *Subscriber, n int) []Message {
	t.Helper()
	out := make([]Message, 0, n)
	for i := 0; i < n; i++ {
		m, ok := s.Pop()
		if !ok {
			t.Fatalf("Pop returned !ok at %d/%d", i, n)
		}
		out = append(out, m)
	}
	return out
}

func TestFanOutOnlyToMatchingSubscribers(t *testing.T) {
	b := New()
	finals := b.Subscribe("finals", []string{protocol.TopicTransFinal})
	partials := b.Subscribe("partials", []string{protocol.TopicTransPartial})
	all := b.Subscribe("all", []string{protocol.TopicAll})

	if b.Subscribers() != 3 {
		t.Fatalf("subscribers=%d", b.Subscribers())
	}

	b.Publish(protocol.TopicTransFinal, map[string]any{"text": "one"})
	if len(drain(t, finals, 1)) != 1 {
		t.Fatal("finals subscriber missed the event")
	}
	if len(drain(t, all, 1)) != 1 {
		t.Fatal("wildcard subscriber missed the event")
	}

	b.Publish(protocol.TopicTransPartial, map[string]any{"text": "tw"})
	if len(drain(t, partials, 1)) != 1 {
		t.Fatal("partials subscriber missed the event")
	}
	if len(drain(t, all, 1)) != 1 {
		t.Fatal("wildcard subscriber missed the partial")
	}
}

func TestSequenceIsPerTopicAndMonotonic(t *testing.T) {
	b := New()
	s := b.Subscribe("s", []string{protocol.TopicAll})
	for i := 0; i < 5; i++ {
		b.Publish(protocol.TopicTransPartial, map[string]any{"i": i})
	}
	seq, _ := b.Publish(protocol.TopicTransFinal, map[string]any{})
	if seq != 1 {
		t.Fatalf("first final should be seq 1, got %d", seq)
	}
	got := drain(t, s, 6)
	for i, m := range got[:5] {
		if m.Seq != uint64(i+1) {
			t.Fatalf("partial %d has seq %d", i, m.Seq)
		}
	}
	if b.Seq(protocol.TopicTransPartial) != 5 {
		t.Fatalf("topic seq=%d", b.Seq(protocol.TopicTransPartial))
	}
}

// A saturated queue drops its oldest disposable frame and keeps the newest.
func TestPartialsDropOldestUnderBackpressure(t *testing.T) {
	b := New()
	s := b.Subscribe("slow", []string{protocol.TopicAll})

	total := SoftCap + 100
	for i := 0; i < total; i++ {
		b.Publish(protocol.TopicTransPartial, map[string]any{"i": i})
	}

	q := s.queue
	q.mu.Lock()
	pending := q.pending()
	first := q.items[q.head].Seq
	last := q.items[len(q.items)-1].Seq
	q.mu.Unlock()

	if pending != SoftCap {
		t.Fatalf("pending=%d want %d (the queue must stay bounded)", pending, SoftCap)
	}
	if last != uint64(total) {
		t.Fatalf("newest partial missing: last seq %d want %d", last, total)
	}
	if first != uint64(total-SoftCap+1) {
		t.Fatalf("oldest kept seq %d want %d", first, total-SoftCap+1)
	}
	if _, dropped := b.Publish(protocol.TopicTransPartial, nil); len(dropped) > 0 {
		t.Fatal("a soft-cap drop must not evict the subscriber")
	}
}

// Durable frames are never dropped: the queue may exceed the soft cap for them.
func TestFinalsAreNeverDropped(t *testing.T) {
	b := New()
	s := b.Subscribe("slow", []string{protocol.TopicAll})

	total := SoftCap + 100
	for i := 0; i < total; i++ {
		b.Publish(protocol.TopicTransFinal, map[string]any{"i": i})
	}
	q := s.queue
	q.mu.Lock()
	pending := q.pending()
	q.mu.Unlock()
	if pending != total {
		t.Fatalf("pending=%d want %d (finals must never be dropped)", pending, total)
	}

	got := drain(t, s, total)
	for i, m := range got {
		if m.Disposable {
			t.Fatalf("final %d is flagged disposable", i)
		}
	}
}

// A partial arriving at a queue that holds only durable frames is dropped
// rather than evicting anything durable.
func TestPartialDroppedWhenQueueIsAllFinals(t *testing.T) {
	b := New()
	s := b.Subscribe("slow", []string{protocol.TopicAll})
	for i := 0; i < SoftCap; i++ {
		b.Publish(protocol.TopicTransFinal, map[string]any{"i": i})
	}
	b.Publish(protocol.TopicTransPartial, map[string]any{"late": true})

	q := s.queue
	q.mu.Lock()
	pending := q.pending()
	first := q.items[q.head].Seq
	last := q.items[len(q.items)-1]
	q.mu.Unlock()
	if pending != SoftCap {
		t.Fatalf("pending=%d want %d", pending, SoftCap)
	}
	if first != 1 {
		t.Fatalf("a durable frame was dropped: oldest is now seq %d", first)
	}
	if last.Disposable {
		t.Fatal("the incoming partial should have been dropped, not queued")
	}
}

// Past the hard cap the subscriber is evicted, which the server turns into a
// closed connection — never a silent loss.
func TestSubscriberIsEvictedPastHardCap(t *testing.T) {
	b := New()
	s := b.Subscribe("stuck", []string{protocol.TopicAll})

	var dropped []*Subscriber
	for i := 0; i < HardCap+10; i++ {
		_, d := b.Publish(protocol.TopicTransFinal, map[string]any{"i": i})
		dropped = append(dropped, d...)
	}
	if len(dropped) == 0 {
		t.Fatal("expected the stuck subscriber to be reported as dropped")
	}
	if dropped[0] != s {
		t.Fatalf("dropped the wrong subscriber: %v", dropped[0].Name)
	}
	if !s.Evicted() {
		t.Fatal("subscriber should report Evicted")
	}
	// An evicted subscriber is closed immediately: its backlog is discarded
	// rather than walked frame by frame into a socket nobody is reading.
	if _, ok := s.Pop(); ok {
		t.Fatal("Pop should fail at once once evicted")
	}
	if pending := s.queue.pending(); pending != 0 {
		t.Fatalf("eviction left %d frames queued", pending)
	}
	if err := s.queue.push(Message{Topic: "x"}); !errors.Is(err, ErrEvicted) {
		t.Fatalf("push after eviction = %v", err)
	}
}

func TestUnsubscribeAndClose(t *testing.T) {
	b := New()
	s := b.Subscribe("s", []string{protocol.TopicTransFinal})
	b.Publish(protocol.TopicTransFinal, map[string]any{"text": "one"})
	b.Publish(protocol.TopicTransPartial, nil)

	s.RemoveTopics([]string{protocol.TopicTransFinal})
	b.Publish(protocol.TopicTransFinal, map[string]any{"text": "two"})
	if len(drain(t, s, 1)) != 1 {
		t.Fatal("expected only the frame queued before the unsubscribe")
	}

	s.Close()
	if b.Subscribers() != 0 {
		t.Fatalf("close left %d subscribers", b.Subscribers())
	}
	// Frames queued before Close are still delivered, then Pop reports false.
	if _, ok := s.Pop(); ok {
		t.Fatal("Pop should report false after draining a closed subscriber")
	}
}

func TestAddTopicsExtendsSubscription(t *testing.T) {
	b := New()
	s := b.Subscribe("s", []string{protocol.TopicTransFinal})
	s.AddTopics([]string{"result.*"})
	b.Publish("result.bullets", map[string]any{})
	m, ok := s.Pop()
	if !ok || m.Topic != "result.bullets" {
		t.Fatalf("extended subscription did not receive the event: %+v", m)
	}
}

func TestPublishDoesNotBlockOnAStalledSubscriber(t *testing.T) {
	b := New()
	b.Subscribe("stalled", []string{protocol.TopicAll})
	done := make(chan struct{})
	go func() {
		for i := 0; i < SoftCap*3; i++ {
			b.Publish(protocol.TopicTransPartial, map[string]any{"i": i})
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Publish blocked on a subscriber that never reads")
	}
}
