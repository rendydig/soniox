// Package httpapi exposes the hub's debug surface over loopback HTTP.
//
// Deliberately tiny: /healthz for readiness probes and supervisors, /state to
// dump the live snapshot without opening an NDJSON connection. Both are how
// every phase stays inspectable while the UI is not running.
package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"soniox-hub/internal/bus"
	"soniox-hub/internal/dispatch"
	"soniox-hub/internal/store"
)

// Deps are the hub pieces the endpoints read.
type Deps struct {
	Store    *store.Store
	Bus      *bus.Bus
	Dispatch *dispatch.Dispatcher
	Started  time.Time
	Version  string
}

// Handler returns the debug mux.
func Handler(d Deps) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":   "ok",
			"version":  d.Version,
			"uptime_s": time.Since(d.Started).Seconds(),
		})
	})

	mux.HandleFunc("/state", func(w http.ResponseWriter, r *http.Request) {
		out := map[string]any{}
		if d.Store != nil {
			out["state"] = d.Store.Snapshot()
		}
		if d.Bus != nil {
			out["subscribers"] = d.Bus.Subscribers()
		}
		if d.Dispatch != nil {
			out["dispatch"] = d.Dispatch.Stats()
		}
		out["uptime_s"] = time.Since(d.Started).Seconds()
		writeJSON(w, http.StatusOK, out)
	})

	return mux
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}
