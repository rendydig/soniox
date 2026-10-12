package sched

import (
	"sync/atomic"
	"testing"
	"time"
)

// A burst of Arms must produce exactly one firing, after the last Arm's quiet
// period — the "wait until the speaker pauses" behaviour of the controllers.
func TestDebounceRearmProducesOneFire(t *testing.T) {
	var fires atomic.Int64
	d := NewDebounce(60*time.Millisecond, func() { fires.Add(1) })
	defer d.Stop()

	for i := 0; i < 5; i++ {
		d.Arm()
		time.Sleep(15 * time.Millisecond)
	}
	if got := fires.Load(); got != 0 {
		t.Fatalf("fired %d times before the quiet period elapsed", got)
	}
	if !d.Pending() {
		t.Fatal("a firing should still be pending")
	}
	time.Sleep(150 * time.Millisecond)
	if got := fires.Load(); got != 1 {
		t.Fatalf("fires=%d want 1", got)
	}
	if d.Pending() {
		t.Fatal("no firing should be pending after it ran")
	}
	if d.Fires() != 1 {
		t.Fatalf("Fires()=%d", d.Fires())
	}
}

func TestDebounceCancelPreventsFiring(t *testing.T) {
	var fires atomic.Int64
	d := NewDebounce(40*time.Millisecond, func() { fires.Add(1) })
	defer d.Stop()

	d.Arm()
	d.Cancel()
	time.Sleep(120 * time.Millisecond)
	if got := fires.Load(); got != 0 {
		t.Fatalf("canceled debounce fired %d times", got)
	}
	if d.Pending() {
		t.Fatal("Pending() should be false after Cancel")
	}
}

// Fire runs a pending callback immediately (the manual hotkey path).
func TestDebounceFireIsImmediate(t *testing.T) {
	var fires atomic.Int64
	d := NewDebounce(time.Hour, func() { fires.Add(1) })
	defer d.Stop()

	d.Arm()
	start := time.Now()
	d.Fire()
	if elapsed := time.Since(start); elapsed > 200*time.Millisecond {
		t.Fatalf("Fire took %s", elapsed)
	}
	if fires.Load() != 1 {
		t.Fatalf("fires=%d want 1", fires.Load())
	}
	if d.Pending() {
		t.Fatal("nothing should remain pending")
	}
	// Firing again without re-arming is a no-op.
	d.Fire()
	if fires.Load() != 1 {
		t.Fatalf("unarmed Fire fired again: %d", fires.Load())
	}
}

func TestDebounceSetDurationTakesEffectOnNextArm(t *testing.T) {
	var fires atomic.Int64
	d := NewDebounce(time.Hour, func() { fires.Add(1) })
	defer d.Stop()

	d.SetDuration(30 * time.Millisecond)
	if d.Duration() != 30*time.Millisecond {
		t.Fatalf("Duration=%s", d.Duration())
	}
	d.Arm()
	time.Sleep(120 * time.Millisecond)
	if fires.Load() != 1 {
		t.Fatalf("fires=%d want 1", fires.Load())
	}
}

func TestDebounceStopDisables(t *testing.T) {
	var fires atomic.Int64
	d := NewDebounce(30*time.Millisecond, func() { fires.Add(1) })
	d.Arm()
	d.Stop()
	d.Arm() // ignored after Stop
	time.Sleep(100 * time.Millisecond)
	if fires.Load() != 0 {
		t.Fatalf("stopped debounce fired %d times", fires.Load())
	}
}

func TestTickerFiresAndAdvancesDeadline(t *testing.T) {
	var fires atomic.Int64
	tk := NewTicker(40*time.Millisecond, func() { fires.Add(1) })
	defer tk.Close()

	if tk.Running() {
		t.Fatal("a new ticker should be stopped")
	}
	tk.Start()
	first := tk.NextAt()
	if first.IsZero() {
		t.Fatal("NextAt should be set once started")
	}
	if tk.Interval() != 40*time.Millisecond {
		t.Fatalf("Interval=%s", tk.Interval())
	}
	time.Sleep(150 * time.Millisecond)
	if got := fires.Load(); got < 2 {
		t.Fatalf("fires=%d want at least 2", got)
	}
	if !tk.NextAt().After(first) {
		t.Fatalf("deadline did not advance: %s then %s", first, tk.NextAt())
	}

	tk.Stop()
	if tk.Running() || !tk.NextAt().IsZero() {
		t.Fatal("Stop must clear the deadline")
	}
	after := fires.Load()
	time.Sleep(100 * time.Millisecond)
	if fires.Load() != after {
		t.Fatal("ticker kept firing after Stop")
	}
}
