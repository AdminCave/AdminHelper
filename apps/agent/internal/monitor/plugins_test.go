// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"testing"
)

func TestGetFloat(t *testing.T) {
	cases := []struct {
		name     string
		m        map[string]any
		key      string
		fallback float64
		want     float64
	}{
		{"float64", map[string]any{"k": 3.5}, "k", -1, 3.5},
		{"int", map[string]any{"k": 7}, "k", -1, 7},
		{"json.Number", map[string]any{"k": json.Number("2.25")}, "k", -1, 2.25},
		{"json.Number int", map[string]any{"k": json.Number("42")}, "k", -1, 42},
		// Invalid json.Number: Float64() fails, the error is discarded -> 0.
		{"json.Number invalid", map[string]any{"k": json.Number("abc")}, "k", -1, 0},
		{"string -> fallback", map[string]any{"k": "5"}, "k", -1, -1},
		{"bool -> fallback", map[string]any{"k": true}, "k", -1, -1},
		{"missing key -> fallback", map[string]any{"x": 1.0}, "k", 9, 9},
		{"nil map -> fallback", nil, "k", 9, 9},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := getFloat(c.m, c.key, c.fallback); got != c.want {
				t.Errorf("getFloat(%v, %q, %v) = %v, erwartet %v",
					c.m, c.key, c.fallback, got, c.want)
			}
		})
	}
}
