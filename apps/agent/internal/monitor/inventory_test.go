// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func svcEntry(unit, active, enabled string) map[string]string {
	return map[string]string{"unit": unit, "active_state": active, "enabled_state": enabled}
}

func TestInventoryHashOrderIndependent(t *testing.T) {
	a := []map[string]string{
		svcEntry("nginx.service", "active", "enabled"),
		svcEntry("sshd.service", "active", "enabled"),
		svcEntry("cron.service", "inactive", "disabled"),
	}
	b := []map[string]string{
		svcEntry("cron.service", "inactive", "disabled"),
		svcEntry("nginx.service", "active", "enabled"),
		svcEntry("sshd.service", "active", "enabled"),
	}
	if inventoryHash(a) != inventoryHash(b) {
		t.Error("Hash haengt von der Reihenfolge ab, erwartet Reihenfolge-Unabhaengigkeit")
	}
}

func TestInventoryHashChangesOnContent(t *testing.T) {
	base := []map[string]string{svcEntry("nginx.service", "active", "enabled")}
	stateChanged := []map[string]string{svcEntry("nginx.service", "inactive", "enabled")}
	unitAdded := []map[string]string{
		svcEntry("nginx.service", "active", "enabled"),
		svcEntry("redis.service", "active", "enabled"),
	}
	if inventoryHash(base) == inventoryHash(stateChanged) {
		t.Error("Hash unveraendert trotz geaendertem active_state")
	}
	if inventoryHash(base) == inventoryHash(unitAdded) {
		t.Error("Hash unveraendert trotz neuer Unit")
	}
}

func TestShouldSendFullInventory(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	recent := &inventoryState{Hash: "h1", LastFullSentUnix: now.Add(-5 * time.Minute).Unix()}
	stale := &inventoryState{Hash: "h1", LastFullSentUnix: now.Add(-61 * time.Minute).Unix()}

	cases := []struct {
		name string
		st   *inventoryState
		hash string
		want bool
	}{
		{"State fehlt/kaputt", nil, "h1", true},
		{"Hash unveraendert, kuerzlich gesendet", recent, "h1", false},
		{"Hash geaendert", recent, "h2", true},
		{"Intervall abgelaufen", stale, "h1", true},
	}
	for _, c := range cases {
		if got := shouldSendFullInventory(c.st, c.hash, now); got != c.want {
			t.Errorf("%s: shouldSendFullInventory = %v, erwartet %v", c.name, got, c.want)
		}
	}
}

func TestInventoryStateRoundtrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")

	if st := loadInventoryState(path); st != nil {
		t.Errorf("fehlende Datei: erwartet nil, bekam %+v", st)
	}

	want := inventoryState{Hash: "abc123", LastFullSentUnix: 1_700_000_000}
	if err := saveInventoryState(path, want); err != nil {
		t.Fatalf("saveInventoryState: %v", err)
	}
	got := loadInventoryState(path)
	if got == nil || *got != want {
		t.Errorf("Roundtrip: erwartet %+v, bekam %+v", want, got)
	}

	if err := os.WriteFile(path, []byte("{kaputt"), 0600); err != nil {
		t.Fatal(err)
	}
	if st := loadInventoryState(path); st != nil {
		t.Errorf("kaputte Datei: erwartet nil, bekam %+v", st)
	}
}

func testReport(services []map[string]string) map[string]any {
	return map[string]any{
		"systemd": map[string]any{
			"failed":           []string{},
			"enabled_inactive": []string{},
			"all_services":     services,
		},
	}
}

func TestThrottleInventory(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "state.json")
	services := []map[string]string{svcEntry("nginx.service", "active", "enabled")}
	now := time.Unix(1_700_000_000, 0)

	// 1) No state file -> full send, state returned for persisting.
	report := testReport(services)
	newState, sentFull := throttleInventory(report, statePath, now)
	if !sentFull {
		t.Fatal("ohne State-Datei: erwartet Full-Send")
	}
	if _, ok := report["systemd"].(map[string]any)["all_services"]; !ok {
		t.Fatal("Full-Send: all_services darf nicht entfernt werden")
	}
	if err := saveInventoryState(statePath, newState); err != nil {
		t.Fatal(err)
	}

	// 2) Unchanged inventory, shortly after -> all_services stripped,
	// legacy keys untouched.
	report = testReport(services)
	_, sentFull = throttleInventory(report, statePath, now.Add(5*time.Minute))
	if sentFull {
		t.Error("unveraendertes Inventar: erwartet Drosselung")
	}
	systemd := report["systemd"].(map[string]any)
	if _, ok := systemd["all_services"]; ok {
		t.Error("gedrosselt: all_services muss entfernt sein")
	}
	if _, ok := systemd["failed"]; !ok {
		t.Error("gedrosselt: failed (alerting-relevant) muss erhalten bleiben")
	}
	if _, ok := systemd["enabled_inactive"]; !ok {
		t.Error("gedrosselt: enabled_inactive muss erhalten bleiben")
	}

	// 3) Changed inventory -> full send again.
	report = testReport([]map[string]string{svcEntry("nginx.service", "failed", "enabled")})
	_, sentFull = throttleInventory(report, statePath, now.Add(10*time.Minute))
	if !sentFull {
		t.Error("geaendertes Inventar: erwartet Full-Send")
	}

	// 4) Unchanged, but full-send interval elapsed -> full send.
	report = testReport(services)
	_, sentFull = throttleInventory(report, statePath, now.Add(inventoryFullInterval+time.Minute))
	if !sentFull {
		t.Error("Intervall abgelaufen: erwartet Full-Send")
	}
}
