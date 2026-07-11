// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import "testing"

// round1/round2 are applied to every collected metric (cpu, mem, load, temps,
// disk), so a rounding bug skews the whole push. They use math.Round (round half
// away from zero — correct for both signs, unlike the old int(f*10+0.5) which
// skewed negatives toward zero, audit 2.62). The half-boundary cases use fp-exact
// inputs (0.25 = 1/4, 0.125 = 1/8) so the assertions don't depend on float noise.
func TestRound1(t *testing.T) {
	cases := []struct {
		in   float64
		want float64
	}{
		{0.0, 0.0},
		{0.24, 0.2}, // below the .x5 boundary -> down
		{0.25, 0.3}, // exactly on the boundary (fp-exact) -> up
		{0.75, 0.8}, // boundary (fp-exact) -> up
		{42.34, 42.3},
		{42.36, 42.4},
		{99.99, 100.0},
		{-42.34, -42.3}, // 2.62: old int-truncation gave -42.2 here
		{-42.36, -42.4},
		{-0.25, -0.3}, // boundary, away from zero
	}
	for _, c := range cases {
		if got := round1(c.in); got != c.want {
			t.Errorf("round1(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}

func TestRound2(t *testing.T) {
	cases := []struct {
		in   float64
		want float64
	}{
		{0.0, 0.0},
		{1.234, 1.23},
		{1.236, 1.24},
		{0.125, 0.13},   // boundary (fp-exact) -> up
		{0.375, 0.38},   // boundary (fp-exact) -> up
		{-1.234, -1.23}, // 2.62: negatives now round correctly
		{-1.236, -1.24},
	}
	for _, c := range cases {
		if got := round2(c.in); got != c.want {
			t.Errorf("round2(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}
