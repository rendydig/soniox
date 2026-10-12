package protocol

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"
)

func TestEncodeDecodeRoundTrip(t *testing.T) {
	in := &Envelope{
		Type:    TypePublish,
		Topic:   TopicTransFinal,
		ID:      "abc",
		Seq:     7,
		Payload: map[string]any{"source": "host", "text": "hello"},
	}
	b, err := Encode(in)
	if err != nil {
		t.Fatalf("Encode: %v", err)
	}
	if !bytes.HasSuffix(b, []byte("\n")) {
		t.Fatalf("frame must be newline-terminated, got %q", b)
	}
	out, err := Decode(b)
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	if out.Type != in.Type || out.Topic != in.Topic || out.Seq != in.Seq {
		t.Fatalf("round trip mismatch: %+v", out)
	}
	if out.Payload["text"] != "hello" {
		t.Fatalf("payload lost: %+v", out.Payload)
	}
}

func TestEncodedPayloadOmitsZeroFields(t *testing.T) {
	b, err := Encode(&Envelope{Type: TypeHelloOK})
	if err != nil {
		t.Fatal(err)
	}
	if got := string(b); got != "{\"type\":\"hello_ok\"}\n" {
		t.Fatalf("unexpected frame: %s", got)
	}
}

// A reader must see frames back one at a time, in order, no matter how the
// bytes are chunked by the network.
func TestLineReaderFraming(t *testing.T) {
	stream := `{"type":"event","topic":"a","seq":1}` + "\n" +
		`{"type":"event","topic":"a","seq":2}` + "\n" +
		`{"type":"event","topic":"a","seq":3}`

	lr := NewLineReader(strings.NewReader(stream))
	var seqs []uint64
	for {
		env, err := lr.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatalf("Read: %v", err)
		}
		seqs = append(seqs, env.Seq)
	}
	if len(seqs) != 3 || seqs[0] != 1 || seqs[1] != 2 || seqs[2] != 3 {
		t.Fatalf("expected 1,2,3 got %v", seqs)
	}
}

// Numbers must survive a decode/encode cycle unchanged: 1 is not 1.0.
func TestDecodePreservesNumberForm(t *testing.T) {
	env, err := Decode([]byte(`{"type":"publish","payload":{"n":1,"big":9007199254740993,"f":1.5}}`))
	if err != nil {
		t.Fatal(err)
	}
	b, err := Encode(env)
	if err != nil {
		t.Fatal(err)
	}
	got := string(b)
	for _, want := range []string{`"n":1`, `"big":9007199254740993`, `"f":1.5`} {
		if !strings.Contains(got, want) {
			t.Fatalf("re-encoded frame lost %s: %s", want, got)
		}
	}
	if strings.Contains(got, "1.0") {
		t.Fatalf("ints were converted to floats: %s", got)
	}
}

func TestDecodeRejectsMissingType(t *testing.T) {
	if _, err := Decode([]byte(`{"topic":"a"}`)); err == nil {
		t.Fatal("expected an error for a frame without a type")
	}
	if _, err := Decode([]byte(`not json`)); err == nil {
		t.Fatal("expected an error for malformed JSON")
	}
}

func TestLineReaderRejectsOversizeFrame(t *testing.T) {
	huge := strings.Repeat("x", MaxLineBytes+1024)
	lr := NewLineReader(strings.NewReader(`{"type":"publish","payload":{"blob":"` + huge + `"}}`))
	_, err := lr.Read()
	if !errors.Is(err, ErrLineTooLong) {
		t.Fatalf("expected ErrLineTooLong, got %v", err)
	}
}

func TestLineReaderToleratesMissingFinalNewline(t *testing.T) {
	lr := NewLineReader(strings.NewReader(`{"type":"hello"}`))
	env, err := lr.Read()
	if err != nil {
		t.Fatalf("Read: %v", err)
	}
	if env.Type != TypeHello {
		t.Fatalf("got %+v", env)
	}
	if _, err := lr.Read(); !errors.Is(err, io.EOF) {
		t.Fatalf("expected EOF, got %v", err)
	}
}

func TestMatch(t *testing.T) {
	cases := []struct {
		pattern, topic string
		want           bool
	}{
		{TopicAll, "anything.at.all", true},
		{"transcription.final", "transcription.final", true},
		{"transcription.final", "transcription.partial", false},
		{"result.*", "result.bullets", true},
		{"result.*", "job.bullets", false},
	}
	for _, c := range cases {
		if got := Match(c.pattern, c.topic); got != c.want {
			t.Errorf("Match(%q,%q)=%v want %v", c.pattern, c.topic, got, c.want)
		}
	}
}

func TestIsDisposable(t *testing.T) {
	if !IsDisposable(TopicTransPartial) {
		t.Fatal("partials are disposable")
	}
	if IsDisposable(TopicTransFinal) {
		t.Fatal("finals are durable")
	}
}
