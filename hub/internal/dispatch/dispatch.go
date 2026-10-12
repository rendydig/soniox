// Package dispatch routes self-contained jobs to the worker agents.
//
// A job is exactly what today's worker constructors receive — the store has
// already resolved the window, the profile, and the conversation — so an agent
// stays a pure function of its input.
//
// One job of a given kind runs at a time. A newer job of the same kind
// supersedes an older *queued* one (the newest state is always the useful one),
// which is how the controllers' `_rerun_pending` flag generalizes: the job that
// finishes first wins, then the single pending job goes out.
package dispatch

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"sync"
)

// Job kinds — one per agent entry point.
const (
	KindAutoReply       = "auto_reply"
	KindImageReply      = "image_reply"
	KindManualTranslate = "manual_translate"
	KindBullets         = "bullets"
	KindPickup          = "pickup"
)

// ErrNoAgent is returned when a job is queued for an agent that is not
// connected yet; the job is held and sent as soon as that agent registers.
var ErrNoAgent = errors.New("dispatch: agent not connected")

// Job is one unit of work handed to an agent.
type Job struct {
	ID      string         `json:"job_id"`
	Kind    string         `json:"kind"`
	Agent   string         `json:"agent"`
	Payload map[string]any `json:"payload"`
	// Attempts counts how many times the job has been handed out, so a
	// restarted agent can be told to resume rather than restart from scratch.
	Attempts int `json:"-"`
}

// Sender delivers a job to one agent connection.
type Sender interface {
	SendJob(job *Job) error
}

// Result is what a finished job reports back.
type Result struct {
	JobID   string         `json:"job_id"`
	Kind    string         `json:"kind"`
	Payload map[string]any `json:"payload"`
}

// Stats is a cheap observability snapshot.
type Stats struct {
	InFlight   int
	Pending    int
	Unsent     int
	Completed  uint64
	Superseded uint64
}

type Dispatcher struct {
	mu         sync.Mutex
	agents     map[string]Sender
	inflight   map[string]*Job   // job ID -> job
	byKind     map[string]string // kind -> in-flight job ID
	pending    map[string]*Job   // kind -> newest superseding job
	unsent     map[string]*Job   // job ID -> job waiting for its agent
	completed  uint64
	superseded uint64
}

// New returns an empty dispatcher.
func New() *Dispatcher {
	return &Dispatcher{
		agents:   map[string]Sender{},
		inflight: map[string]*Job{},
		byKind:   map[string]string{},
		pending:  map[string]*Job{},
		unsent:   map[string]*Job{},
	}
}

// Register attaches an agent connection and flushes any jobs that were waiting
// for it. It returns how many jobs were flushed.
func (d *Dispatcher) Register(agent string, s Sender) int {
	d.mu.Lock()
	d.agents[agent] = s
	var flush []*Job
	for id, job := range d.unsent {
		if job.Agent == agent {
			flush = append(flush, job)
			delete(d.unsent, id)
		}
	}
	d.mu.Unlock()

	for _, job := range flush {
		// Route through Submit so the normal in-flight bookkeeping applies.
		_ = d.Submit(job)
	}
	return len(flush)
}

// Unregister detaches an agent and re-queues its in-flight jobs as pending, so
// a restarted agent picks the work back up.
func (d *Dispatcher) Unregister(agent string) int {
	d.mu.Lock()
	delete(d.agents, agent)
	var requeued []*Job
	for id, job := range d.inflight {
		if job.Agent != agent {
			continue
		}
		delete(d.inflight, id)
		if d.byKind[job.Kind] == id {
			delete(d.byKind, job.Kind)
		}
		job.Attempts++
		requeued = append(requeued, job)
	}
	d.mu.Unlock()

	for _, job := range requeued {
		_ = d.Submit(job)
	}
	return len(requeued)
}

// Submit hands a job to its agent. When a job of the same kind is already in
// flight the new one becomes the single pending job (superseding any older
// pending job of that kind) and nil is returned.
func (d *Dispatcher) Submit(job *Job) error {
	if job.ID == "" {
		job.ID = NewJobID()
	}
	d.mu.Lock()
	if _, ok := d.byKind[job.Kind]; ok {
		if old, had := d.pending[job.Kind]; had {
			_ = old
			d.superseded++
		}
		d.pending[job.Kind] = job
		d.mu.Unlock()
		return nil
	}
	sender, ok := d.agents[job.Agent]
	if !ok {
		d.unsent[job.ID] = job
		d.mu.Unlock()
		return ErrNoAgent
	}
	d.claimLocked(job)
	d.mu.Unlock()

	return d.deliver(sender, job)
}

// claimLocked records job as the in-flight job of its kind.
func (d *Dispatcher) claimLocked(job *Job) {
	d.inflight[job.ID] = job
	d.byKind[job.Kind] = job.ID
}

func (d *Dispatcher) deliver(sender Sender, job *Job) error {
	if err := sender.SendJob(job); err != nil {
		d.mu.Lock()
		delete(d.inflight, job.ID)
		if d.byKind[job.Kind] == job.ID {
			delete(d.byKind, job.Kind)
		}
		d.unsent[job.ID] = job
		d.mu.Unlock()
		return err
	}
	return nil
}

// Complete retires a finished job and returns the pending job that now becomes
// current, if any (already delivered).
func (d *Dispatcher) Complete(jobID string) (*Job, bool) {
	d.mu.Lock()
	job, ok := d.inflight[jobID]
	if !ok {
		d.mu.Unlock()
		return nil, false
	}
	delete(d.inflight, jobID)
	if d.byKind[job.Kind] == jobID {
		delete(d.byKind, job.Kind)
	}
	d.completed++
	next := d.pending[job.Kind]
	delete(d.pending, job.Kind)
	sender := d.agents[job.Agent]
	if next != nil {
		d.claimLocked(next)
	}
	d.mu.Unlock()

	if next == nil {
		return nil, true
	}
	if sender == nil {
		d.mu.Lock()
		delete(d.inflight, next.ID)
		delete(d.byKind, next.Kind)
		d.unsent[next.ID] = next
		d.mu.Unlock()
		return next, true
	}
	_ = d.deliver(sender, next)
	return next, true
}

// KindOf returns the kind of an in-flight job.
func (d *Dispatcher) KindOf(jobID string) (string, bool) {
	d.mu.Lock()
	defer d.mu.Unlock()
	job, ok := d.inflight[jobID]
	if !ok {
		return "", false
	}
	return job.Kind, true
}

// Stats returns the current counters.
func (d *Dispatcher) Stats() Stats {
	d.mu.Lock()
	defer d.mu.Unlock()
	return Stats{
		InFlight:   len(d.inflight),
		Pending:    len(d.pending),
		Unsent:     len(d.unsent),
		Completed:  d.completed,
		Superseded: d.superseded,
	}
}

// NewJobID returns a short random job identifier.
func NewJobID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "job-fallback"
	}
	return hex.EncodeToString(b[:])
}
