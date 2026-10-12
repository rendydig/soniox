package dispatch

import (
	"errors"
	"sync"
	"testing"
)

type fakeAgent struct {
	mu   sync.Mutex
	jobs []*Job
	fail bool
}

func (f *fakeAgent) SendJob(job *Job) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.fail {
		return errors.New("agent unavailable")
	}
	f.jobs = append(f.jobs, job)
	return nil
}

func (f *fakeAgent) sent() []*Job {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]*Job(nil), f.jobs...)
}

func (f *fakeAgent) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.jobs)
}

func job(kind, agent string) *Job {
	return &Job{ID: NewJobID(), Kind: kind, Agent: agent, Payload: map[string]any{}}
}

func TestSubmitDeliversToRegisteredAgent(t *testing.T) {
	d := New()
	a := &fakeAgent{}
	d.Register("bullets-agent", a)

	if err := d.Submit(job(KindBullets, "bullets-agent")); err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if a.count() != 1 {
		t.Fatalf("agent received %d jobs", a.count())
	}
	if got := d.Stats(); got.InFlight != 1 || got.Completed != 0 {
		t.Fatalf("stats=%+v", got)
	}
}

// A job for an agent that is not connected yet is held, then delivered on
// Register — the app can publish work before the agents finish starting.
func TestJobIsHeldUntilAgentRegisters(t *testing.T) {
	d := New()
	pending := job(KindBullets, "bullets-agent")
	if err := d.Submit(pending); !errors.Is(err, ErrNoAgent) {
		t.Fatalf("Submit = %v want ErrNoAgent", err)
	}
	if d.Stats().Unsent != 1 {
		t.Fatalf("stats=%+v", d.Stats())
	}

	a := &fakeAgent{}
	if flushed := d.Register("bullets-agent", a); flushed != 1 {
		t.Fatalf("Register flushed %d jobs", flushed)
	}
	if a.count() != 1 || a.sent()[0].ID != pending.ID {
		t.Fatalf("held job was not delivered: %+v", a.sent())
	}
	if d.Stats().Unsent != 0 {
		t.Fatal("unsent queue should be empty")
	}
}

// One job of a kind runs at a time; a newer one supersedes an older queued one
// and goes out when the in-flight job finishes.
func TestNewerJobSupersedesQueuedOne(t *testing.T) {
	d := New()
	a := &fakeAgent{}
	d.Register("bullets-agent", a)

	first := job(KindBullets, "bullets-agent")
	if err := d.Submit(first); err != nil {
		t.Fatal(err)
	}
	second := job(KindBullets, "bullets-agent")
	third := job(KindBullets, "bullets-agent")
	if err := d.Submit(second); err != nil {
		t.Fatal(err)
	}
	if err := d.Submit(third); err != nil {
		t.Fatal(err)
	}
	if a.count() != 1 {
		t.Fatalf("only the in-flight job should have been sent, got %d", a.count())
	}
	if got := d.Stats(); got.Pending != 1 || got.Superseded != 1 {
		t.Fatalf("stats=%+v", got)
	}

	next, known := d.Complete(first.ID)
	if !known {
		t.Fatal("Complete did not recognize the in-flight job")
	}
	if next == nil || next.ID != third.ID {
		t.Fatalf("the newest queued job should run next, got %+v", next)
	}
	if a.count() != 2 || a.sent()[1].ID != third.ID {
		t.Fatalf("superseding job was not delivered: %+v", a.sent())
	}
	if d.Stats().Completed != 1 {
		t.Fatalf("stats=%+v", d.Stats())
	}
}

func TestDifferentKindsRunConcurrently(t *testing.T) {
	d := New()
	a := &fakeAgent{}
	d.Register("agent", a)
	d.Submit(job(KindBullets, "agent"))
	d.Submit(job(KindPickup, "agent"))
	d.Submit(job(KindAutoReply, "agent"))
	if a.count() != 3 {
		t.Fatalf("kinds should not block each other, got %d", a.count())
	}
	if d.Stats().InFlight != 3 {
		t.Fatalf("stats=%+v", d.Stats())
	}
}

func TestCompleteUnknownJobIsIgnored(t *testing.T) {
	d := New()
	if _, known := d.Complete("nope"); known {
		t.Fatal("an unknown job id must not be reported as known")
	}
}

// A failed delivery is not lost: it is re-queued for the next Register.
func TestFailedDeliveryIsRequeued(t *testing.T) {
	d := New()
	a := &fakeAgent{fail: true}
	d.Register("agent", a)
	j := job(KindPickup, "agent")
	if err := d.Submit(j); err == nil {
		t.Fatal("expected the delivery error to propagate")
	}
	if d.Stats().Unsent != 1 || d.Stats().InFlight != 0 {
		t.Fatalf("stats=%+v", d.Stats())
	}
	a.fail = false
	if flushed := d.Register("agent", a); flushed != 1 {
		t.Fatalf("flushed=%d", flushed)
	}
	if a.count() != 1 {
		t.Fatalf("job not re-delivered: %+v", a.sent())
	}
}

// An agent that dies mid-job has its work re-queued with an incremented attempt
// count, and picks it back up when it reconnects.
func TestUnregisterRequeuesInFlightJobs(t *testing.T) {
	d := New()
	a := &fakeAgent{}
	d.Register("agent", a)
	j := job(KindAutoReply, "agent")
	d.Submit(j)

	if requeued := d.Unregister("agent"); requeued != 1 {
		t.Fatalf("requeued=%d", requeued)
	}
	if d.Stats().Unsent != 1 {
		t.Fatalf("stats=%+v", d.Stats())
	}
	if j.Attempts != 1 {
		t.Fatalf("Attempts=%d", j.Attempts)
	}

	b := &fakeAgent{}
	d.Register("agent", b)
	if b.count() != 1 || b.sent()[0].ID != j.ID {
		t.Fatalf("restarted agent did not resume the job: %+v", b.sent())
	}
	if b.sent()[0].Attempts != 1 {
		t.Fatal("attempt count must survive the restart")
	}
}

func TestNewJobIDIsUnique(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 1000; i++ {
		id := NewJobID()
		if id == "" || seen[id] {
			t.Fatalf("duplicate or empty job id %q", id)
		}
		seen[id] = true
	}
}
