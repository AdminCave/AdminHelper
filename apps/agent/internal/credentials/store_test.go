// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package credentials

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func storePath(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "monitor", "credentials.json")
}

// writeFile stores f at path the way Set writes it, for entries Set would not write.
func writeFile(t *testing.T, path string, f any) {
	t.Helper()
	if err := update(context.Background(), path, func(map[string]Credential) error { return nil }); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(f)
	if err != nil {
		t.Fatal(err)
	}
	writeRaw(t, path, data)
}

// writeRaw replaces the content of the file at path, which keeps its mode, owner and DACL.
func writeRaw(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestAMissingFileHoldsNoCredential(t *testing.T) {
	creds, err := Load(storePath(t))
	if err != nil || len(creds) != 0 || creds == nil {
		t.Fatalf("Load = %v, %v; want an empty map", creds, err)
	}
}

func TestSetStoresASecretUnderItsRefWithANewID(t *testing.T) {
	ctx := context.Background()
	path := storePath(t)
	if err := Set(ctx, path, "db/main", "s3cr3t pass"); err != nil {
		t.Fatal(err)
	}
	if err := Set(ctx, path, "web:admin@host", "other"); err != nil {
		t.Fatal(err)
	}
	creds, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	first := creds["db/main"]
	if first.Secret != "s3cr3t pass" || !idPattern.MatchString(first.ID) {
		t.Fatalf("db/main = %+v", first)
	}
	if got := Refs(creds); fmt.Sprint(got) != "[db/main web:admin@host]" {
		t.Fatalf("Refs = %v", got)
	}

	// The same secret set anew gets a new id: the access brake waits for exactly that.
	if err := Set(ctx, path, "db/main", "s3cr3t pass"); err != nil {
		t.Fatal(err)
	}
	creds, err = Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if again := creds["db/main"]; again.Secret != first.Secret || again.ID == first.ID {
		t.Fatalf("set anew: %+v, before %+v; want the same secret with a new id", again, first)
	}
	if creds["web:admin@host"].Secret != "other" {
		t.Fatalf("the other credential changed: %+v", creds["web:admin@host"])
	}
}

func TestSetRefusesARefTheMonitoringCannotName(t *testing.T) {
	for _, ref := range []string{"", "/db", "db/", "db//main", "-db", "db main", "db/.x", "ä", strings.Repeat("a", 256)} {
		if err := Set(context.Background(), storePath(t), ref, "secret"); err == nil {
			t.Errorf("Set(%q) = nil; want an error", ref)
		}
	}
	if err := Set(context.Background(), storePath(t), strings.Repeat("a", 255), "secret"); err != nil {
		t.Errorf("a ref of 255 characters: %v", err)
	}
}

func TestSetRefusesASecretItCannotPresentWithoutQuotingIt(t *testing.T) {
	cases := map[string]string{
		"empty":          "",
		"newline":        "pass\nX-Injected: 1",
		"carriage":       "pass\rword",
		"nul":            "pass\x00word",
		"tab":            "pass\tword",
		"del":            "pass\x7fword",
		"not utf-8":      "pass\xffword",
		"too long":       strings.Repeat("p", MaxSecretBytes+1),
		"cut off at 4 K": strings.Repeat("p", 4<<10),
	}
	for name, secret := range cases {
		err := Set(context.Background(), storePath(t), "db", secret)
		if err == nil {
			t.Errorf("%s: Set = nil; want an error", name)
			continue
		}
		if secret != "" && strings.Contains(err.Error(), "pass") {
			t.Errorf("%s: the error quotes the secret: %v", name, err)
		}
	}
	if err := Set(context.Background(), storePath(t), "db", strings.Repeat("ü", MaxSecretBytes/2)); err != nil {
		t.Errorf("a secret of %d bytes: %v", MaxSecretBytes, err)
	}
}

func TestDeleteRemovesOneCredential(t *testing.T) {
	ctx := context.Background()
	path := storePath(t)
	for _, ref := range []string{"a", "b"} {
		if err := Set(ctx, path, ref, "secret-"+ref); err != nil {
			t.Fatal(err)
		}
	}
	if err := Delete(ctx, path, "a"); err != nil {
		t.Fatal(err)
	}
	creds, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(Refs(creds)) != "[b]" {
		t.Fatalf("after Delete: %v", Refs(creds))
	}
	if err := Delete(ctx, path, "a"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Delete of a missing ref = %v; want ErrNotFound", err)
	}
}

func TestSetStopsAtAsManyRefsAsTheMonitoringKeeps(t *testing.T) {
	ctx := context.Background()
	path := storePath(t)
	full := map[string]Credential{}
	for i := range MaxCredentials {
		full[fmt.Sprintf("ref%d", i)] = Credential{Secret: "s", ID: strings.Repeat("0", 32)}
	}
	writeFile(t, path, file{Version: fileVersion, Credentials: full})
	if err := Set(ctx, path, "one-more", "s"); err == nil {
		t.Fatal("Set beyond MaxCredentials = nil; want an error")
	}
	if err := Set(ctx, path, "ref7", "new"); err != nil {
		t.Fatalf("set anew at the limit: %v", err)
	}
	creds, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(creds) != MaxCredentials || creds["ref7"].Secret != "new" {
		t.Fatalf("%d credentials, ref7 %+v", len(creds), creds["ref7"])
	}
}

func TestLoadLeavesOutEntriesSetWouldNotWrite(t *testing.T) {
	path := storePath(t)
	id := strings.Repeat("ab", 16)
	writeFile(t, path, file{Version: fileVersion, Credentials: map[string]Credential{
		"good":    {Secret: "s", ID: id},
		"bad ref": {Secret: "s", ID: id},
		"no-id":   {Secret: "s"},
		"upper":   {Secret: "s", ID: strings.ToUpper(id)},
		"empty":   {ID: id},
		"line":    {Secret: "a\nb", ID: id},
	}})
	creds, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(Refs(creds)) != "[good]" {
		t.Fatalf("Load = %v; want only good", Refs(creds))
	}
}

func TestLoadRefusesAFileOfAnotherFormWithoutQuotingIt(t *testing.T) {
	cases := map[string]string{
		"cut off":       `{"version":1,"credentials":{"db":{"secret":"s3cr3t`,
		"bad character": `{"version":1,"credentials":{"db":{"secret":"s3cr3t"}x}}`,
		"version 2":     `{"version":2,"credentials":{"db":{"secret":"s3cr3t","id":"` + strings.Repeat("0", 32) + `"}}}`,
		"no version":    `{"credentials":{}}`,
		"a list":        `["s3cr3t"]`,
		"bad escape":    `{"version":1,"credentials":{"db":{"secret":"s3cr3\Q","id":"` + strings.Repeat("0", 32) + `"}}}`,
	}
	for name, content := range cases {
		path := storePath(t)
		writeFile(t, path, file{Version: fileVersion})
		writeRaw(t, path, []byte(content))
		creds, err := Load(path)
		if err == nil {
			t.Errorf("%s: Load = %v; want an error", name, creds)
			continue
		}
		// Exactly this message: the decoder's own would quote a character of the file.
		if want := fmt.Sprintf("%s is no credentials file of version %d", path, fileVersion); err.Error() != want {
			t.Errorf("%s: Load error = %q, want %q", name, err, want)
		}
	}
}

func TestSetKeepsTheOtherSetsMadeAtTheSameTime(t *testing.T) {
	ctx := context.Background()
	path := storePath(t)
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for i := range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			errs <- Set(ctx, path, fmt.Sprintf("ref%d", i), "secret")
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	creds, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(creds) != 8 {
		t.Fatalf("%d of 8 credentials stored: %v", len(creds), Refs(creds))
	}
}

func TestASetThatFailsLeavesTheFileAsItWas(t *testing.T) {
	ctx := context.Background()
	path := storePath(t)
	if err := Set(ctx, path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	before, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := Set(ctx, path, "db", "bad\nsecret"); err == nil {
		t.Fatal("Set = nil; want an error")
	}
	if err := Delete(ctx, path, "nothing"); err == nil {
		t.Fatal("Delete = nil; want an error")
	}
	after, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if after["db"] != before["db"] {
		t.Fatalf("after failed changes: %+v, before %+v", after["db"], before["db"])
	}
	entries, err := filepath.Glob(filepath.Join(filepath.Dir(path), ".credentials-*.tmp"))
	if err != nil || len(entries) != 0 {
		t.Fatalf("temp files left: %v, %v", entries, err)
	}
}
