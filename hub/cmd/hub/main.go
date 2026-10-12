// Command hub is the central state hub for the Soniox desktop app.
//
// It owns all live session state and the message bus: publishers (the Soniox
// workers, the hotkeys, the UI) publish topics, subscribers (the UI, the
// browser bridge, the worker agents) receive ordered events. It never touches
// audio, so nothing here can abort the PortAudio stream.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"soniox-hub/internal/bus"
	"soniox-hub/internal/dispatch"
	"soniox-hub/internal/httpapi"
	"soniox-hub/internal/persist"
	"soniox-hub/internal/server"
	"soniox-hub/internal/store"
)

// Version is bumped when the wire protocol changes incompatibly.
const Version = "0.1.0"

func main() {
	var (
		addr     = flag.String("addr", envOr("HUB_ADDR", "127.0.0.1:8770"), "NDJSON/TCP listen address")
		httpAddr = flag.String("http", envOr("HUB_HTTP_ADDR", "127.0.0.1:8771"), "debug HTTP address (- to disable)")
		token    = flag.String("token", os.Getenv("HUB_TOKEN"), "handshake token (empty = no auth)")
		events   = flag.String("events", "", "append-only JSONL event log path (empty = off)")
		snapshot = flag.String("snapshot", "", "session snapshot path (empty = off)")
		debounce = flag.Duration("snapshot-debounce", 2*time.Second, "snapshot write debounce")
		version  = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()

	if *version {
		fmt.Println("soniox-hub", Version)
		return
	}

	logger := log.New(os.Stderr, "", log.LstdFlags|log.Lmicroseconds)
	logf := func(format string, args ...any) { logger.Printf(format, args...) }

	st := store.New()
	bs := bus.New()
	dp := dispatch.New()

	pw, err := persist.New(persist.Options{
		EventsPath:   *events,
		SnapshotPath: *snapshot,
		Debounce:     *debounce,
		Snapshot:     func() any { return st.Snapshot() },
		Logf:         logf,
	})
	if err != nil {
		logger.Fatalf("hub: persist init: %v", err)
	}
	defer pw.Close()

	srv := server.New(server.Options{
		Addr:     *addr,
		Token:    *token,
		Store:    st,
		Bus:      bs,
		Dispatch: dp,
		Persist:  pw,
		Logf:     logf,
	})
	bound, err := srv.Listen()
	if err != nil {
		logger.Fatalf("hub: listen %s: %v", *addr, err)
	}
	logger.Printf("hub %s listening on %s (events=%q snapshot=%q)", Version, bound, *events, *snapshot)

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	var httpSrv *http.Server
	if *httpAddr != "-" && *httpAddr != "" {
		ln, err := net.Listen("tcp", *httpAddr)
		if err != nil {
			logger.Fatalf("hub: http listen %s: %v", *httpAddr, err)
		}
		httpSrv = &http.Server{
			Handler: httpapi.Handler(httpapi.Deps{
				Store:    st,
				Bus:      bs,
				Dispatch: dp,
				Started:  time.Now(),
				Version:  Version,
			}),
			ReadHeaderTimeout: 5 * time.Second,
		}
		go func() {
			logger.Printf("hub: debug HTTP on http://%s", ln.Addr())
			if err := httpSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
				logger.Printf("hub: http: %v", err)
			}
		}()
	}

	go func() {
		if err := srv.Serve(ctx); err != nil {
			logger.Printf("hub: serve: %v", err)
			cancel()
		}
	}()

	<-ctx.Done()
	logger.Printf("hub: shutting down")

	if httpSrv != nil {
		shutdownCtx, done := context.WithTimeout(context.Background(), 2*time.Second)
		defer done()
		_ = httpSrv.Shutdown(shutdownCtx)
	}
	_ = srv.Shutdown()
	if err := pw.Flush(); err != nil {
		logger.Printf("hub: final snapshot: %v", err)
	}
	logger.Printf("hub: stopped")
}

func envOr(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}
