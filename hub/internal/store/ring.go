// Package store owns the hub's live session state.
//
// The discipline mirrors the Python SessionStore that this replaces: writers
// replace values, never mutate them in place, and readers get copies under a
// read lock. Bounded by construction — every list is backed by a fixed-capacity
// ring that overwrites the oldest entry instead of reallocating.
package store

// Ring is a fixed-capacity buffer that overwrites the oldest entry once full.
// It never reallocates: the backing array is allocated once by NewRing.
type Ring[T any] struct {
	buf   []T
	start int
	count int
}

// NewRing returns a ring with the given capacity (clamped to at least 1).
func NewRing[T any](capacity int) *Ring[T] {
	if capacity < 1 {
		capacity = 1
	}
	return &Ring[T]{buf: make([]T, capacity)}
}

// Cap returns the fixed capacity.
func (r *Ring[T]) Cap() int { return len(r.buf) }

// Len returns how many entries are currently stored.
func (r *Ring[T]) Len() int { return r.count }

// Push appends v, overwriting the oldest entry when the ring is full.
func (r *Ring[T]) Push(v T) {
	if r.count < len(r.buf) {
		r.buf[(r.start+r.count)%len(r.buf)] = v
		r.count++
		return
	}
	r.buf[r.start] = v
	r.start = (r.start + 1) % len(r.buf)
}

// Slice returns the entries oldest-to-newest as a fresh slice.
func (r *Ring[T]) Slice() []T {
	out := make([]T, r.count)
	for i := 0; i < r.count; i++ {
		out[i] = r.buf[(r.start+i)%len(r.buf)]
	}
	return out
}

// Last returns the newest entry and whether one exists.
func (r *Ring[T]) Last() (T, bool) {
	var zero T
	if r.count == 0 {
		return zero, false
	}
	return r.buf[(r.start+r.count-1)%len(r.buf)], true
}

// Clear drops every entry, keeping the backing array.
func (r *Ring[T]) Clear() {
	var zero T
	for i := 0; i < r.count; i++ {
		r.buf[(r.start+i)%len(r.buf)] = zero
	}
	r.start = 0
	r.count = 0
}

// Set replaces the contents with items, keeping only the newest Cap() of them.
// The ring's own storage is reused.
func (r *Ring[T]) Set(items []T) {
	if len(items) > len(r.buf) {
		items = items[len(items)-len(r.buf):]
	}
	r.Clear()
	for _, v := range items {
		r.Push(v)
	}
}
