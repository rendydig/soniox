// Package sched owns the hub's timing: the debounces that today live in the
// Qt controllers (auto-reply, "Last Picked Up") and the polling interval that
// drives automatic bullet-point updates.
//
// A Debounce fires once, after the quiet period that follows its most recent
// Arm. Re-arming restarts the clock, which is exactly the "wait until the
// speaker pauses" behaviour the controllers implement with a QTimer.
package sched

import (
	"sync"
	"time"
)

// Debounce is a re-armable one-shot timer.
type Debounce struct {
	mu      sync.Mutex
	d       time.Duration
	fn      func()
	timer   *time.Timer
	gen     uint64
	fires   uint64
	stopped bool
}

// NewDebounce returns an unarmed debounce that will call fn after d.
func NewDebounce(d time.Duration, fn func()) *Debounce {
	return &Debounce{d: d, fn: fn}
}

// Duration returns the configured quiet period.
func (b *Debounce) Duration() time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.d
}

// SetDuration changes the quiet period; it takes effect on the next Arm.
func (b *Debounce) SetDuration(d time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.d = d
}

// Arm (re)starts the quiet period. Every call pushes the deadline out, so a
// burst of events produces exactly one firing.
func (b *Debounce) Arm() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.stopped {
		return
	}
	b.gen++
	gen := b.gen
	if b.timer != nil {
		b.timer.Stop()
	}
	b.timer = time.AfterFunc(b.d, func() {
		b.mu.Lock()
		// A newer Arm superseded this timer.
		if b.stopped || gen != b.gen {
			b.mu.Unlock()
			return
		}
		b.timer = nil
		b.fires++
		fn := b.fn
		b.mu.Unlock()
		if fn != nil {
			fn()
		}
	})
}

// Cancel stops a pending firing without running it.
func (b *Debounce) Cancel() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.gen++
	if b.timer != nil {
		b.timer.Stop()
		b.timer = nil
	}
}

// Fire runs the callback immediately if a firing is pending.
func (b *Debounce) Fire() {
	b.mu.Lock()
	if b.stopped || b.timer == nil {
		b.mu.Unlock()
		return
	}
	b.gen++
	b.timer.Stop()
	b.timer = nil
	b.fires++
	fn := b.fn
	b.mu.Unlock()
	if fn != nil {
		fn()
	}
}

// Pending reports whether a firing is scheduled.
func (b *Debounce) Pending() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.timer != nil
}

// Fires returns how many times the callback has run.
func (b *Debounce) Fires() uint64 {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.fires
}

// Stop cancels and permanently disables the debounce.
func (b *Debounce) Stop() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.stopped = true
	if b.timer != nil {
		b.timer.Stop()
		b.timer = nil
	}
}

// Ticker calls fn every interval until stopped. It also reports the next
// deadline so the UI can render a countdown from the same clock.
type Ticker struct {
	mu       sync.Mutex
	interval time.Duration
	fn       func()
	timer    *time.Timer
	gen      uint64
	nextAt   time.Time
	running  bool
	stopped  bool
}

// NewTicker returns a stopped ticker.
func NewTicker(interval time.Duration, fn func()) *Ticker {
	return &Ticker{interval: interval, fn: fn}
}

// Start (re)starts the ticker, scheduling the first fire one interval out.
func (t *Ticker) Start() {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.stopped {
		return
	}
	t.gen++
	gen := t.gen
	if t.timer != nil {
		t.timer.Stop()
	}
	t.running = true
	t.nextAt = time.Now().Add(t.interval)
	t.timer = time.AfterFunc(t.interval, func() { t.tick(gen) })
}

func (t *Ticker) tick(gen uint64) {
	t.mu.Lock()
	if t.stopped || !t.running || gen != t.gen {
		t.mu.Unlock()
		return
	}
	fn := t.fn
	fireAt := t.nextAt
	t.nextAt = fireAt.Add(t.interval)
	d := time.Until(t.nextAt)
	if d < 0 {
		d = 0
	}
	t.timer = time.AfterFunc(d, func() { t.tick(gen) })
	t.mu.Unlock()
	if fn != nil {
		fn()
	}
}

// Stop halts the ticker.
func (t *Ticker) Stop() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.gen++
	t.running = false
	if t.timer != nil {
		t.timer.Stop()
		t.timer = nil
	}
}

// Close stops the ticker permanently.
func (t *Ticker) Close() {
	t.Stop()
	t.mu.Lock()
	t.stopped = true
	t.mu.Unlock()
}

// NextAt returns the epoch deadline of the next fire (zero when stopped).
func (t *Ticker) NextAt() time.Time {
	t.mu.Lock()
	defer t.mu.Unlock()
	if !t.running {
		return time.Time{}
	}
	return t.nextAt
}

// Interval returns the configured period.
func (t *Ticker) Interval() time.Duration {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.interval
}

// Running reports whether the ticker is armed.
func (t *Ticker) Running() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.running
}
