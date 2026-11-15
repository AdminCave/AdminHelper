// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"
)

// phpS, phpI and phpA write values the way PHP's serialize() does.
func phpS(s string) string { return fmt.Sprintf("s:%d:\"%s\";", len(s), s) }
func phpI(n int64) string  { return fmt.Sprintf("i:%d;", n) }
func phpA(pairs ...string) string {
	return fmt.Sprintf("a:%d:{%s}", len(pairs)/2, strings.Join(pairs, ""))
}

// wpEvent is one event of the option cron: schedule, args and, for a recurring one, interval.
func wpEvent(schedule string, args string) string {
	if schedule == "" {
		return phpA(phpS("schedule"), "b:0;", phpS("args"), args)
	}
	return phpA(phpS("schedule"), phpS(schedule), phpS("args"), args, phpS("interval"), phpI(43200))
}

func TestWPCronCountsEventsAndTheOverdueOnes(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	hash := "40cd750bba9870f18aada2478b24840a"
	cron := phpA(
		// Due an hour ago: two hooks, one of them with two events (other arguments).
		phpI(now.Unix()-3600), phpA(
			phpS("wp_version_check"), phpA(phpS(hash), wpEvent("twicedaily", "a:0:{}")),
			phpS("my_plugin_job"), phpA(
				phpS("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), wpEvent("", phpA(phpI(0), "d:1.5;", phpI(1), "N;")),
				phpS("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), wpEvent("", phpA(phpI(0), `O:8:"stdClass":1:{`+phpS("x")+"b:1;}")),
			),
		),
		// Due five minutes ago: not yet overdue.
		phpI(now.Unix()-300), phpA(phpS("wp_scheduled_delete"), phpA(phpS(hash), wpEvent("daily", "a:0:{}"))),
		// Due tomorrow.
		phpI(now.Unix()+86400), phpA(phpS("wp_update_plugins"), phpA(phpS(hash), wpEvent("twicedaily", "a:0:{}"))),
		phpS("version"), phpI(2),
	)
	got, err := wpCronCounts([]byte(cron), now)
	if err != nil {
		t.Fatalf("wpCronCounts: %v", err)
	}
	want := map[string]any{"events": int64(5), "overdue": int64(3), "oldest_overdue_s": int64(3600)}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestWPCronCountsNothingWithoutEvents(t *testing.T) {
	got, err := wpCronCounts([]byte(phpA(phpS("version"), phpI(2))), time.Unix(1_800_000_000, 0))
	if err != nil {
		t.Fatalf("wpCronCounts: %v", err)
	}
	if fmt.Sprint(got) != fmt.Sprint(map[string]any{"events": int64(0), "overdue": int64(0), "oldest_overdue_s": int64(0)}) {
		t.Fatalf("got %v", got)
	}
}

func TestWPCronRefusesAnOptionOfAnotherForm(t *testing.T) {
	secret := "hook_name_that_must_not_leak"
	good := phpA(phpI(1), phpA(phpS(secret), phpA(phpS("h"), wpEvent("", "a:0:{}"))))
	deep := strings.Repeat("a:1:{i:0;", wpCronMaxDepth+2) + "N;" + strings.Repeat("}", wpCronMaxDepth+2)
	for name, data := range map[string]string{
		"empty":                   "",
		"truncated":               good[:len(good)-1],
		"trailing bytes":          good + "N;",
		"a string too long":       `a:1:{i:1;s:99:"` + secret + `";}`,
		"a string too short":      `a:1:{i:1;s:2:"` + secret + `";}`,
		"a count too high":        `a:2:{i:1;a:0:{}}`,
		"a reference":             `a:1:{i:1;R:1;}`,
		"custom serialization":    `a:1:{i:1;C:3:"Foo":0:{}}`,
		"an array as key":         `a:1:{a:0:{}i:1;}`,
		"a bool of 2":             `a:1:{i:1;b:2;}`,
		"a number too long":       `a:1:{i:123456789012345678901;a:0:{}}`,
		"not an array":            phpS(secret),
		"a timestamp of a string": phpA(phpI(1), phpS(secret)),
		"a hook of a string":      phpA(phpI(1), phpA(phpS(secret), phpS("x"))),
		"nested too deep":         deep,
		"too large":               phpA(phpS("version"), phpS(strings.Repeat("x", wpCronMaxBytes))),
	} {
		t.Run(name, func(t *testing.T) {
			_, err := wpCronCounts([]byte(data), time.Unix(1_800_000_000, 0))
			if !errors.Is(err, errPHPForm) {
				t.Fatalf("got %v, want errPHPForm", err)
			}
			if strings.Contains(err.Error(), secret) {
				t.Fatalf("the error quotes the option: %v", err)
			}
		})
	}
}

func TestWPCronStopsAtTooManyValues(t *testing.T) {
	var b strings.Builder
	n := wpCronMaxValues / 2
	fmt.Fprintf(&b, "a:%d:{", n)
	for i := range n {
		fmt.Fprintf(&b, "i:%d;N;", i)
	}
	b.WriteString("}")
	if _, err := parsePHP([]byte(b.String())); !errors.Is(err, errPHPForm) {
		t.Fatalf("got %v, want errPHPForm", err)
	}
}
