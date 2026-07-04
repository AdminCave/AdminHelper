// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"
)

// The all_services inventory (100-300 units, mostly static) does not need to
// ride along on every 5-minute push. It is re-sent in full only when it
// changed or after this interval; the small alerting-relevant keys (failed,
// enabled_inactive, watched/services) are always sent.
const inventoryFullInterval = time.Hour

// inventoryState is the persisted throttle state.
type inventoryState struct {
	Hash             string `json:"hash"`
	LastFullSentUnix int64  `json:"last_full_sent_unix"`
}

// inventoryHash computes a SHA-256 over a normalized, deterministically
// sorted representation of all_services. The entry order from
// collectServiceHealth is map-iteration order (random), so the hash must be
// order-independent.
func inventoryHash(services []ServiceEntry) string {
	lines := make([]string, 0, len(services))
	for _, svc := range services {
		lines = append(lines, svc["unit"]+"\t"+svc["active_state"]+"\t"+svc["enabled_state"])
	}
	sort.Strings(lines)
	sum := sha256.Sum256([]byte(strings.Join(lines, "\n")))
	return fmt.Sprintf("%x", sum)
}

// loadInventoryState reads the persisted state; any error (missing file,
// corrupt JSON) yields nil, which forces a full send.
func loadInventoryState(path string) *inventoryState {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var st inventoryState
	if err := json.Unmarshal(data, &st); err != nil || st.Hash == "" {
		return nil
	}
	return &st
}

// saveInventoryState persists the throttle state. A failure here must never
// prevent a push — callers only log it (next push then sends full again).
func saveInventoryState(path string, st inventoryState) error {
	data, err := json.Marshal(st)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}

// shouldSendFullInventory decides whether all_services goes into this push:
// state missing/corrupt, hash changed, or full-send interval elapsed.
func shouldSendFullInventory(st *inventoryState, hash string, now time.Time) bool {
	if st == nil {
		return true
	}
	if st.Hash != hash {
		return true
	}
	return now.Unix()-st.LastFullSentUnix >= int64(inventoryFullInterval/time.Second)
}

// throttleInventory strips systemd.all_services from the report when the
// inventory is unchanged and recently sent. Returns the state to persist
// after a SUCCESSFUL full send (persisting before/without success would let
// the server miss a full inventory for up to an hour) and whether the report
// still contains the full inventory.
func throttleInventory(report map[string]any, statePath string, now time.Time) (inventoryState, bool) {
	systemd, ok := report["systemd"].(map[string]any)
	if !ok {
		return inventoryState{}, false
	}
	allServices, ok := systemd["all_services"].([]ServiceEntry)
	if !ok {
		// Unexpected shape: leave the report untouched (full send), no state.
		return inventoryState{}, false
	}

	hash := inventoryHash(allServices)
	if shouldSendFullInventory(loadInventoryState(statePath), hash, now) {
		return inventoryState{Hash: hash, LastFullSentUnix: now.Unix()}, true
	}
	// Key removed entirely: the monitoring service distinguishes "key missing
	// -> fall back to the always-sent legacy keys" from "empty list ->
	// genuinely no services" (ServiceProcessChecker._evaluate_auto).
	delete(systemd, "all_services")
	return inventoryState{}, false
}
