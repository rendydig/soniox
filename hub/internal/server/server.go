// Package server implements the hub's NDJSON/TCP listener.
//
// One goroutine accepts, two goroutines per connection: a reader that decodes
// frames, and a writer fed by the connection's outbound queue. Bus messages and
// direct replies share that queue so a single writer owns the socket.
package server

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"soniox-hub/internal/bus"
	"soniox-hub/internal/dispatch"
	"soniox-hub/internal/persist"
	"soniox-hub/internal/protocol"
	"soniox-hub/internal/store"
)

// Options configure a Server.
type Options struct {
	Addr     string
	Token    string
	Store    *store.Store
	Bus      *bus.Bus
	Dispatch *dispatch.Dispatcher
	Persist  *persist.Writer
	Logf     func(format string, args ...any)
}

// Server is the hub's listener.
type Server struct {
	opts Options

	mu       sync.Mutex
	conns    map[uint64]*conn
	bySub    map[uint64]*conn
	nextID   uint64
	listener net.Listener

	accepted atomic.Uint64
	rejected atomic.Uint64
}

// New returns an unstarted server.
func New(opts Options) *Server {
	if opts.Logf == nil {
		opts.Logf = func(string, ...any) {}
	}
	return &Server{
		opts:  opts,
		conns: map[uint64]*conn{},
		bySub: map[uint64]*conn{},
	}
}

// Listen opens the listener, returning the bound address.
func (s *Server) Listen() (net.Addr, error) {
	ln, err := net.Listen("tcp", s.opts.Addr)
	if err != nil {
		return nil, err
	}
	s.listener = ln
	return ln.Addr(), nil
}

// Addr returns the bound address (empty before Listen).
func (s *Server) Addr() net.Addr {
	if s.listener == nil {
		return nil
	}
	return s.listener.Addr()
}

// Serve accepts connections until ctx is cancelled.
func (s *Server) Serve(ctx context.Context) error {
	if s.listener == nil {
		if _, err := s.Listen(); err != nil {
			return err
		}
	}
	go func() {
		<-ctx.Done()
		_ = s.Shutdown()
	}()

	for {
		c, err := s.listener.Accept()
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		s.accepted.Add(1)
		go s.handle(c)
	}
}

// Shutdown closes the listener and every live connection.
func (s *Server) Shutdown() error {
	var err error
	if s.listener != nil {
		err = s.listener.Close()
	}
	s.mu.Lock()
	conns := make([]*conn, 0, len(s.conns))
	for _, c := range s.conns {
		conns = append(conns, c)
	}
	s.mu.Unlock()
	for _, c := range conns {
		c.close()
	}
	return err
}

// Stats reports connection counters (accepted / rejected handshakes).
func (s *Server) Stats() (accepted, rejected uint64) {
	return s.accepted.Load(), s.rejected.Load()
}

// --- connection -------------------------------------------------------------

const (
	outQueueDepth = 256
	// writeTimeout bounds a single frame write: a peer that stops reading must
	// not pin a goroutine forever.
	writeTimeout = 10 * time.Second
	// closeGrace is how long the writer gets to flush queued frames after the
	// connection is closed, before the socket is force-closed under it.
	closeGrace = 2 * time.Second
)

type conn struct {
	id     uint64
	server *Server
	raw    net.Conn
	out    chan *protocol.Envelope
	done   chan struct{}

	role string
	name string

	mu        sync.Mutex
	sub       *bus.Subscriber
	closeOnce sync.Once
	closed    atomic.Bool
}

func (s *Server) handle(raw net.Conn) {
	s.mu.Lock()
	s.nextID++
	id := s.nextID
	c := &conn{
		id:     id,
		server: s,
		raw:    raw,
		out:    make(chan *protocol.Envelope, outQueueDepth),
		done:   make(chan struct{}),
	}
	s.conns[id] = c
	s.mu.Unlock()

	writerDone := make(chan struct{})
	go c.writeLoop(writerDone)

	// Teardown order matters: close() only signals the writer, and the writer
	// owns raw.Close(). That way the final frame (e.g. a hello_err) is flushed
	// before the socket goes away, and closing it unblocks the reader.
	defer func() {
		c.close()
		<-writerDone
		s.mu.Lock()
		delete(s.conns, id)
		if c.sub != nil {
			delete(s.bySub, c.sub.ID)
		}
		s.mu.Unlock()
	}()

	// Handshake: the first frame must be hello.
	lr := protocol.NewLineReader(raw)
	env, err := lr.Read()
	if err != nil {
		if !errors.Is(err, io.EOF) {
			s.opts.Logf("hub: conn %d handshake read: %v", id, err)
		}
		return
	}
	if env.Type != protocol.TypeHello {
		s.rejected.Add(1)
		s.opts.Logf("hub: conn %d expected hello, got %q", id, env.Type)
		c.send(&protocol.Envelope{Type: protocol.TypeHelloErr, Error: "expected hello"})
		return
	}
	if s.opts.Token != "" && env.Token != s.opts.Token {
		s.rejected.Add(1)
		s.opts.Logf("hub: conn %d bad token (role=%s)", id, env.Role)
		c.send(&protocol.Envelope{Type: protocol.TypeHelloErr, Error: "bad token"})
		return
	}
	c.role = env.Role
	if c.role == "" {
		c.role = protocol.RoleUI
	}
	c.name = env.Name
	if c.name == "" {
		c.name = c.role + "-" + strconv.FormatUint(id, 10)
	}
	s.opts.Logf("hub: %s connected as %s (conn %d)", c.name, c.role, id)
	c.send(&protocol.Envelope{Type: protocol.TypeHelloOK})

	// Read frames until the peer goes away.
	for {
		env, err := lr.Read()
		if err != nil {
			if err != io.EOF && !errors.Is(err, net.ErrClosed) {
				s.opts.Logf("hub: %s read: %v", c.name, err)
			}
			return
		}
		s.dispatch(c, env)
	}
}

func (c *conn) send(env *protocol.Envelope) {
	if c.closed.Load() {
		return
	}
	select {
	case c.out <- env:
	case <-c.done:
	}
}

func (c *conn) writeLoop(done chan<- struct{}) {
	defer close(done)
	// The writer owns the socket: it is the only goroutine that writes, so it is
	// also the one that closes, after the queued frames have been flushed.
	defer func() { _ = c.raw.Close() }()
	for {
		select {
		case env := <-c.out:
			if err := c.writeFrame(env); err != nil {
				return
			}
		case <-c.done:
			// Drain whatever is already queued before closing.
			for {
				select {
				case env := <-c.out:
					if err := c.writeFrame(env); err != nil {
						return
					}
				default:
					return
				}
			}
		}
	}
}

// writeFrame serializes and writes one frame under a deadline.
func (c *conn) writeFrame(env *protocol.Envelope) error {
	b, err := protocol.Encode(env)
	if err != nil {
		c.server.opts.Logf("hub: %s encode: %v", c.name, err)
		return nil
	}
	_ = c.raw.SetWriteDeadline(time.Now().Add(writeTimeout))
	_, err = c.raw.Write(b)
	return err
}

func (c *conn) close() {
	c.closeOnce.Do(func() {
		c.closed.Store(true)
		close(c.done)
		c.mu.Lock()
		sub := c.sub
		c.mu.Unlock()
		if sub != nil {
			sub.Close()
		}
		// The writer normally closes the socket once its queue has drained. If
		// it is stuck inside a write to a peer that stopped reading, this bounds
		// the leak: closing the socket aborts the pending write.
		time.AfterFunc(closeGrace, func() { _ = c.raw.Close() })
	})
}

// --- message routing --------------------------------------------------------

func (s *Server) dispatch(c *conn, env *protocol.Envelope) {
	switch env.Type {
	case protocol.TypePublish:
		s.onPublish(c, env)
	case protocol.TypeSubscribe:
		s.onSubscribe(c, env)
	case protocol.TypeUnsubscribe:
		c.mu.Lock()
		sub := c.sub
		c.mu.Unlock()
		if sub != nil {
			sub.RemoveTopics(env.Topics)
		}
	case protocol.TypeRequest:
		s.onRequest(c, env)
	case protocol.TypeResult, protocol.TypeResultChunk:
		s.onResult(c, env)
	case protocol.TypeAck:
		// Nothing to do; the frame is purely informational.
	default:
		s.opts.Logf("hub: %s sent unknown type %q", c.name, env.Type)
		c.send(&protocol.Envelope{Type: protocol.TypeError, Error: "unknown type: " + env.Type})
	}
}

func (s *Server) onPublish(c *conn, env *protocol.Envelope) {
	if env.Topic == "" {
		c.send(&protocol.Envelope{Type: protocol.TypeError, Error: "publish without topic"})
		return
	}
	seq, dropped := s.opts.Bus.Publish(env.Topic, env.Payload)

	if s.opts.Store.Apply(env.Topic, env.Payload) {
		s.markDirty()
	}
	s.appendEvent(env.Topic, seq, env.Payload)
	for _, sub := range dropped {
		s.mu.Lock()
		victim := s.bySub[sub.ID]
		s.mu.Unlock()
		if victim != nil {
			s.opts.Logf("hub: evicting %s (queue overflow, topic %s)", victim.name, env.Topic)
			victim.close()
		}
	}
}

func (s *Server) onSubscribe(c *conn, env *protocol.Envelope) {
	c.mu.Lock()
	if c.sub == nil {
		c.mu.Unlock()
		sub := s.opts.Bus.Subscribe(c.name, env.Topics)
		c.mu.Lock()
		c.sub = sub
		s.mu.Lock()
		s.bySub[sub.ID] = c
		s.mu.Unlock()
		go s.fanout(c, sub)
	} else {
		c.sub.AddTopics(env.Topics)
	}
	c.mu.Unlock()
	c.send(&protocol.Envelope{Type: protocol.TypeAck, Action: "subscribe", Topics: env.Topics})
}

// fanout pumps one subscriber's queue into the connection's outbound queue.
// Blocking here is what applies backpressure to the bus, which then drops
// partials and (past the hard cap) evicts the subscriber.
func (s *Server) fanout(c *conn, sub *bus.Subscriber) {
	for {
		msg, ok := sub.Pop()
		if !ok {
			if sub.Evicted() {
				s.opts.Logf("hub: %s evicted", c.name)
			}
			c.close()
			return
		}
		c.send(&protocol.Envelope{
			Type:    protocol.TypeEvent,
			Topic:   msg.Topic,
			Seq:     msg.Seq,
			Ts:      float64(time.Now().UnixNano()) / 1e9,
			Payload: msg.Payload,
		})
	}
}

func (s *Server) onRequest(c *conn, env *protocol.Envelope) {
	ok := true
	var result any
	var errMsg string

	switch env.Op {
	case protocol.OpSnapshot:
		snap := s.opts.Store.Snapshot()
		session, err := jsonValue(snap)
		if err != nil {
			ok, errMsg = false, err.Error()
			break
		}
		result = map[string]any{
			"session":  session,
			"config":   snap.Config,
			"purposes": snap.Purposes,
			"status":   snap.Status,
		}

	case protocol.OpRestore:
		if err := s.opts.Store.Restore(env.Payload); err != nil {
			ok, errMsg = false, err.Error()
			break
		}
		s.markDirty()
		result = map[string]any{"restored": true}

	case protocol.OpReset:
		old := s.opts.Store.Snapshot()
		s.opts.Store.Reset()
		s.markDirty()
		result = map[string]any{"archived_id": old.ID}

	default:
		ok, errMsg = false, fmt.Sprintf("unknown op %q", env.Op)
	}

	reply := &protocol.Envelope{Type: protocol.TypeResponse, ID: env.ID, Result: result, OK: &ok}
	if !ok {
		reply.Error = errMsg
		reply.Result = nil
	}
	c.send(reply)
}

func (s *Server) onResult(c *conn, env *protocol.Envelope) {
	if env.Type == protocol.TypeResultChunk {
		// Streaming partials are relayed verbatim; nothing to book-keep.
		s.opts.Bus.Publish("result.chunk", map[string]any{
			"job_id": env.JobID,
			"text":   env.Text,
		})
		return
	}

	kind, known := s.opts.Dispatch.KindOf(env.JobID)
	next, _ := s.opts.Dispatch.Complete(env.JobID)
	if known && env.Payload != nil {
		switch kind {
		case dispatch.KindAutoReply, dispatch.KindImageReply:
			if text, _ := env.Payload["text"].(string); text != "" {
				s.opts.Store.AppendGeminiResult(map[string]any{
					"text":   text,
					"source": kind,
				})
				s.opts.Persist.MarkDirty()
			}
		}
	}
	if next != nil {
		s.opts.Logf("hub: dispatched queued %s job after %s finished", next.Kind, env.JobID)
	}
}

// --- helpers ----------------------------------------------------------------

func (s *Server) markDirty() {
	if s.opts.Persist != nil {
		s.opts.Persist.MarkDirty()
	}
}

func (s *Server) appendEvent(topic string, seq uint64, payload map[string]any) {
	if s.opts.Persist != nil {
		s.opts.Persist.AppendEvent(topic, seq, payload)
	}
}

// jsonValue normalizes a value through JSON so the response payload is plain
// maps/slices (never a struct with methods the caller cannot see).
func jsonValue(v any) (any, error) {
	b, err := protocol.Encode(&protocol.Envelope{Type: "tmp", Result: v})
	if err != nil {
		return nil, err
	}
	env, err := protocol.Decode(b)
	if err != nil {
		return nil, err
	}
	return env.Result, nil
}
