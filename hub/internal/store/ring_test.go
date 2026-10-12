package store

import (
	"reflect"
	"testing"
)

func TestRingOverwritesOldestAtCapacity(t *testing.T) {
	r := NewRing[int](3)
	if r.Cap() != 3 {
		t.Fatalf("Cap=%d", r.Cap())
	}
	for _, v := range []int{1, 2, 3} {
		r.Push(v)
	}
	if got := r.Slice(); !reflect.DeepEqual(got, []int{1, 2, 3}) {
		t.Fatalf("got %v", got)
	}
	r.Push(4)
	if got := r.Slice(); !reflect.DeepEqual(got, []int{2, 3, 4}) {
		t.Fatalf("after overwrite got %v", got)
	}
	if r.Len() != 3 {
		t.Fatalf("Len=%d", r.Len())
	}
}

// The backing array must be allocated exactly once: capacity is the bound.
func TestRingNeverReallocates(t *testing.T) {
	r := NewRing[int](4)
	ptr := &r.buf[0]
	for i := 0; i < 1000; i++ {
		r.Push(i)
	}
	if &r.buf[0] != ptr {
		t.Fatal("ring reallocated its backing array")
	}
	if len(r.buf) != 4 {
		t.Fatalf("capacity changed: %d", len(r.buf))
	}
}

func TestRingLastAndClear(t *testing.T) {
	r := NewRing[string](2)
	if _, ok := r.Last(); ok {
		t.Fatal("empty ring has no last")
	}
	r.Push("a")
	r.Push("b")
	last, ok := r.Last()
	if !ok || last != "b" {
		t.Fatalf("Last=%q ok=%v", last, ok)
	}
	r.Clear()
	if r.Len() != 0 || r.Cap() != 2 {
		t.Fatalf("Clear must keep capacity: len=%d cap=%d", r.Len(), r.Cap())
	}
	if _, ok := r.Last(); ok {
		t.Fatal("cleared ring has no last")
	}
}

func TestRingSetKeepsNewest(t *testing.T) {
	r := NewRing[int](3)
	r.Set([]int{1, 2, 3, 4, 5})
	if got := r.Slice(); !reflect.DeepEqual(got, []int{3, 4, 5}) {
		t.Fatalf("got %v", got)
	}
	r.Set(nil)
	if r.Len() != 0 {
		t.Fatalf("Len=%d", r.Len())
	}
}

func TestRingClampsZeroCapacity(t *testing.T) {
	r := NewRing[int](0)
	if r.Cap() != 1 {
		t.Fatalf("Cap=%d", r.Cap())
	}
	r.Push(1)
	r.Push(2)
	if got := r.Slice(); !reflect.DeepEqual(got, []int{2}) {
		t.Fatalf("got %v", got)
	}
}
