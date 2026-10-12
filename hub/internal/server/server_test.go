package server

import (
	"context"
	"net"
	"testing"
	"time"

	"soniox-hub/internal/bus"
	"soniox-hub/internal/dispatch"
	"soniox-hub/internal/protocol"
	"soniox-hub/internal/store"
)

type testConn struct {
	t  *testing.T
	c  net.Conn
	lr *protocol.LineReader
}

func newTestServer(t *testing.T, token string) (string, *store.Store, *bus.Bus) {
	t.Helper()
	st := store.New()
	bs := bus.New()
	srv := New(Options{
		Addr:     "127.0.0.1:0",
		Token:    token,
		Store:    st,
		Bus:      bs,
		Dispatch: dispatch.New(),
		Logf:     t.Logf,
	})
	addr, err := srv.Listen()
	if err != nil {
		t.Fatalf("Listen: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); _ = srv.Serve(ctx) }()
	t.Cleanup(func() {
		cancel()
		_ = srv.Shutdown()
		<-done
	})
	return addr.String(), st, bs
}

func dial(t *testing.T, addr string) *testConn {
	t.Helper()
	c, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return &testConn{t: t, c: c, lr: protocol.NewLineReader(c)}
}

func (tc *testConn) send(env *protocol.Envelope) {
	tc.t.Helper()
	b, err := protocol.Encode(env)
	if err != nil {
		tc.t.Fatalf("encode: %v", err)
	}
	if _, err := tc.c.Write(b); err != nil {
		tc.t.Fatalf("write: %v", err)
	}
}

func (tc *testConn) recv() *protocol.Envelope {
	tc.t.Helper()
	if err := tc.c.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		tc.t.Fatalf("deadline: %v", err)
	}
	env, err := tc.lr.Read()
	if err != nil {
		tc.t.Fatalf("read: %v", err)
	}
	return env
}

func hello(t *testing.T, addr, role, name, token string) *testConn {
	t.Helper()
	tc := dial(t, addr)
	tc.send(&protocol.Envelope{Type: protocol.TypeHello, Role: role, Name: name, Token: token})
	got := tc.recv()
	if got.Type != protocol.TypeHelloOK {
		t.Fatalf("handshake failed: %+v", got)
	}
	return tc
}

func TestHandshakeAccepted(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	hello(t, addr, protocol.RoleUI, "ui", "")
}

func TestHandshakeRejectsBadToken(t *testing.T) {
	addr, _, _ := newTestServer(t, "secret")
	tc := dial(t, addr)
	tc.send(&protocol.Envelope{Type: protocol.TypeHello, Role: protocol.RoleUI, Token: "wrong"})
	got := tc.recv()
	if got.Type != protocol.TypeHelloErr || got.Error == "" {
		t.Fatalf("expected hello_err, got %+v", got)
	}
}

func TestHandshakeRejectsNonHelloFirstFrame(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	tc := dial(t, addr)
	tc.send(&protocol.Envelope{Type: protocol.TypePublish, Topic: "x"})
	got := tc.recv()
	if got.Type != protocol.TypeHelloErr {
		t.Fatalf("expected hello_err, got %+v", got)
	}
}

// Publishing from one connection must reach a subscriber on another, in order,
// with monotonically increasing per-topic sequence numbers.
func TestPublishReachesSubscriberInOrder(t *testing.T) {
	addr, st, _ := newTestServer(t, "")
	sub := hello(t, addr, protocol.RoleUI, "ui", "")
	sub.send(&protocol.Envelope{Type: protocol.TypeSubscribe, Topics: []string{protocol.TopicTransFinal}})
	if ack := sub.recv(); ack.Type != protocol.TypeAck {
		t.Fatalf("expected ack, got %+v", ack)
	}

	pub := hello(t, addr, protocol.RolePublisher, "soniox", "")
	for i, text := range []string{"one", "two", "three"} {
		pub.send(&protocol.Envelope{
			Type:  protocol.TypePublish,
			Topic: protocol.TopicTransFinal,
			Payload: map[string]any{
				"source": "host", "text": text, "endpoint": true,
			},
		})
		ev := sub.recv()
		if ev.Type != protocol.TypeEvent || ev.Topic != protocol.TopicTransFinal {
			t.Fatalf("event %d: %+v", i, ev)
		}
		if ev.Seq != uint64(i+1) {
			t.Fatalf("event %d has seq %d", i, ev.Seq)
		}
		if ev.Payload["text"] != text {
			t.Fatalf("event %d payload: %+v", i, ev.Payload)
		}
	}

	// The same publishes must have landed in the store.
	snap := st.Snapshot()
	if len(snap.Transcriptions) != 3 || snap.Transcriptions[2].Text != "three" {
		t.Fatalf("store did not record the finals: %+v", snap.Transcriptions)
	}
	if len(snap.Conversation) != 3 {
		t.Fatalf("conversation=%+v", snap.Conversation)
	}
}

func TestPartialTopicIsFlaggedDisposable(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	sub := hello(t, addr, protocol.RoleUI, "ui", "")
	sub.send(&protocol.Envelope{Type: protocol.TypeSubscribe, Topics: []string{protocol.TopicTransPartial}})
	sub.recv()

	pub := hello(t, addr, protocol.RolePublisher, "soniox", "")
	pub.send(&protocol.Envelope{Type: protocol.TypePublish, Topic: protocol.TopicTransPartial, Payload: map[string]any{"text": "liv"}})
	ev := sub.recv()
	if !protocol.IsDisposable(ev.Topic) {
		t.Fatalf("partial topic should be disposable: %s", ev.Topic)
	}
}

func TestUnsubscribeStopsEvents(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	sub := hello(t, addr, protocol.RoleUI, "ui", "")
	sub.send(&protocol.Envelope{Type: protocol.TypeSubscribe, Topics: []string{protocol.TopicTransFinal}})
	sub.recv()

	pub := hello(t, addr, protocol.RolePublisher, "soniox", "")
	pub.send(&protocol.Envelope{Type: protocol.TypePublish, Topic: protocol.TopicTransFinal, Payload: map[string]any{"text": "a"}})
	sub.recv()

	sub.send(&protocol.Envelope{Type: protocol.TypeUnsubscribe, Topics: []string{protocol.TopicTransFinal}})
	// Nothing acknowledges an unsubscribe; give the server a moment to apply it.
	time.Sleep(100 * time.Millisecond)
	pub.send(&protocol.Envelope{Type: protocol.TypePublish, Topic: protocol.TopicTransFinal, Payload: map[string]any{"text": "b"}})

	if err := sub.c.SetReadDeadline(time.Now().Add(300 * time.Millisecond)); err != nil {
		t.Fatal(err)
	}
	if _, err := sub.lr.Read(); err == nil {
		t.Fatal("a frame arrived after unsubscribe")
	}
}

func TestRequestSnapshotRestoreReset(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	c := hello(t, addr, protocol.RoleUI, "ui", "")

	// Empty snapshot.
	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "r1", Op: protocol.OpSnapshot})
	resp := c.recv()
	if resp.Type != protocol.TypeResponse || resp.ID != "r1" || resp.OK == nil || !*resp.OK {
		t.Fatalf("snapshot response: %+v", resp)
	}
	result, ok := resp.Result.(map[string]any)
	if !ok {
		t.Fatalf("result is %T", resp.Result)
	}
	session, ok := result["session"].(map[string]any)
	if !ok {
		t.Fatalf("session is %T", result["session"])
	}
	if lines, _ := session["transcriptions"].([]any); len(lines) != 0 {
		t.Fatalf("fresh hub should have an empty transcript: %+v", session["transcriptions"])
	}

	// Restore seeds the store.
	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "r2", Op: protocol.OpRestore, Payload: map[string]any{
		"id":             "20261012-060000",
		"transcriptions": []any{map[string]any{"source": "host", "text": "restored", "timestamp": "t"}},
		"bullets":        []any{"b"},
		"speaker":        map[string]any{"name": "Ada"},
		"last_pickup":    "did something",
	}})
	resp = c.recv()
	if resp.ID != "r2" || resp.OK == nil || !*resp.OK {
		t.Fatalf("restore response: %+v", resp)
	}

	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "r3", Op: protocol.OpSnapshot})
	resp = c.recv()
	session = resp.Result.(map[string]any)["session"].(map[string]any)
	if lines := session["transcriptions"].([]any); len(lines) != 1 {
		t.Fatalf("restore did not take: %+v", session["transcriptions"])
	}
	if session["id"] != "20261012-060000" {

		t.Fatalf("id=%v", session["id"])
	}

	// Reset clears the session.
	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "r4", Op: protocol.OpReset})
	resp = c.recv()
	if resp.ID != "r4" || resp.OK == nil || !*resp.OK {
		t.Fatalf("reset response: %+v", resp)
	}
	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "r5", Op: protocol.OpSnapshot})
	resp = c.recv()
	session = resp.Result.(map[string]any)["session"].(map[string]any)
	if lines := session["transcriptions"].([]any); len(lines) != 0 {
		t.Fatalf("reset left lines behind: %+v", session["transcriptions"])
	}
	if session["last_pickup"] != "" {
		t.Fatalf("last_pickup=%v", session["last_pickup"])
	}
}

func TestUnknownRequestOpFails(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	c := hello(t, addr, protocol.RoleUI, "ui", "")
	c.send(&protocol.Envelope{Type: protocol.TypeRequest, ID: "x", Op: "nope"})
	resp := c.recv()
	if resp.OK == nil || *resp.OK {
		t.Fatalf("expected ok=false, got %+v", resp)
	}
	if resp.Error == "" {
		t.Fatal("expected an error message")
	}
}

func TestUnknownTypeReturnsError(t *testing.T) {
	addr, _, _ := newTestServer(t, "")
	c := hello(t, addr, protocol.RoleUI, "ui", "")
	c.send(&protocol.Envelope{Type: "bogus"})
	resp := c.recv()
	if resp.Type != protocol.TypeError {
		t.Fatalf("expected error, got %+v", resp)
	}
}

// A subscriber that never reads must not stall the publisher: it is eventually
// evicted and disconnected.
func TestSlowSubscriberIsEvictedAndDisconnected(t *testing.T) {
	addr, _, bs := newTestServer(t, "")
	slow := hello(t, addr, protocol.RoleUI, "slow", "")
	slow.send(&protocol.Envelope{Type: protocol.TypeSubscribe, Topics: []string{protocol.TopicAll}})
	slow.recv()

	pub := hello(t, addr, protocol.RolePublisher, "soniox", "")

	// Publish until the hub drops the reader that never drains. The precise
	// count depends on how much the socket buffers absorb, so drive it to the
	// observable outcome instead of guessing a number.
	const maxFrames = 60000
	sent := 0
	for ; sent < maxFrames && bs.Subscribers() > 0; sent++ {
		pub.send(&protocol.Envelope{Type: protocol.TypePublish, Topic: protocol.TopicTransFinal, Payload: map[string]any{"text": "x"}})
	}
	if bs.Subscribers() > 0 {
		t.Fatalf("the stalled subscriber was never evicted after %d frames", sent)
	}

	// The hub drops the stalled connection: the read eventually fails for a
	// reason other than the deadline we set here.
	_ = slow.c.SetReadDeadline(time.Now().Add(15 * time.Second))
	for {
		_, err := slow.lr.Read()
		if err == nil {
			continue
		}
		if ne, ok := err.(net.Error); ok && ne.Timeout() {
			t.Fatalf("the stalled connection was never closed: %v", err)
		}
		return
	}
}
