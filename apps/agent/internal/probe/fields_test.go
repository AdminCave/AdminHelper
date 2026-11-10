// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestReleaseSendsTheAskedScalarsAlone(t *testing.T) {
	raw := map[string]any{
		"status":  "OK",
		"up":      true,
		"conns":   12,
		"ratio":   0.5,
		"big":     json.Number("12345678901234567"),
		"token":   "never asked",
		"version": map[string]any{"major": uint8(7), "minor": json.Number("3")},
	}

	got := release(raw, []string{"status", "up", "conns", "ratio", "big", "version.major", "version.minor"})

	want := map[string]any{
		"status": "OK", "up": true, "conns": 12, "ratio": 0.5, "big": json.Number("12345678901234567"),
		"version.major": uint8(7), "version.minor": json.Number("3"),
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("release = %#v\nwant %#v", got, want)
	}
}

func TestReleaseFindsAKeyThatHoldsADot(t *testing.T) {
	raw := map[string]any{
		"mem.used": 7,
		"mem":      map[string]any{"used": 9},
		"a":        map[string]any{"b.c": "deep"},
	}

	got := release(raw, []string{"mem.used", "a.b.c"})

	if got["mem.used"] != 7 || got["a.b.c"] != "deep" {
		t.Fatalf("release = %v, want the whole key first and a dotted key below", got)
	}
}

func TestReleaseLeavesOutWhatIsNoScalar(t *testing.T) {
	raw := map[string]any{
		"list":   []any{1, 2},
		"object": map[string]any{"x": 1},
		"null":   nil,
		"nan":    math.NaN(),
		"inf":    math.Inf(1),
		"inf32":  float32(math.Inf(-1)),
		"bad":    json.Number("1e"),
		"hex":    json.Number("0x10"),
		"lead0":  json.Number("012"),
		"scalar": "x",
		"func":   func() {},
	}

	got := release(raw, []string{"list", "list.0", "object", "null", "nan", "inf", "inf32", "bad", "hex", "lead0", "missing", "scalar.below", "func"})

	if len(got) != 0 {
		t.Fatalf("release = %v, want nothing of these", got)
	}
}

func TestReleaseSendsNothingWithoutFields(t *testing.T) {
	got := release(map[string]any{"status": "OK"}, nil)

	if got == nil || len(got) != 0 {
		t.Fatalf("release = %#v, want an empty map", got)
	}
}

func TestReleaseStopsAtMaxFields(t *testing.T) {
	raw := map[string]any{}
	var fields []string
	for i := range maxFields + 5 {
		key := fmt.Sprintf("f%02d", i)
		raw[key] = i
		fields = append(fields, key)
	}
	// Asked twice, a field counts once.
	fields = append([]string{"f00", "f00", "f01"}, fields...)

	got := release(raw, fields)

	if len(got) != maxFields {
		t.Fatalf("release sent %d fields, want %d", len(got), maxFields)
	}
	if _, ok := got[fmt.Sprintf("f%02d", maxFields-1)]; !ok {
		t.Errorf("release = %v, want the first %d distinct fields", got, maxFields)
	}
	if _, ok := got[fmt.Sprintf("f%02d", maxFields)]; ok {
		t.Errorf("release sent f%02d beyond the cap", maxFields)
	}
}

func TestReleaseCountsAFieldItLeavesOut(t *testing.T) {
	raw := map[string]any{"late": 1}
	var fields []string
	for i := range maxFields {
		fields = append(fields, fmt.Sprintf("missing%d", i))
	}

	got := release(raw, append(fields, "late"))

	if len(got) != 0 {
		t.Fatalf("release = %v, want the cap to count asked fields, not found ones", got)
	}
}

func TestReleaseCleansText(t *testing.T) {
	raw := map[string]any{"long": strings.Repeat("ü", maxTextRunes+10), "nul": "a\x00b\xffc"}

	got := release(raw, []string{"long", "nul"})

	long := got["long"].(string)
	if utf8.RuneCountInString(long) != maxTextRunes {
		t.Errorf("long has %d runes, want %d", utf8.RuneCountInString(long), maxTextRunes)
	}
	if got["nul"] != "ab�c" {
		t.Errorf("nul = %q, want %q", got["nul"], "ab�c")
	}
}
