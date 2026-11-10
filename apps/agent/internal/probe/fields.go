// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"encoding/json"
	"math"
	"regexp"
	"strings"
)

const (
	// maxFields is as many fields of a result as go to the monitoring service.
	maxFields = 32
	// maxTextRunes caps a text value, as the monitoring service cuts it again.
	maxTextRunes = 256
)

// jsonNumber is a number as JSON writes it; a json.Number from a decoder that was handed anything
// else is not sent.
var jsonNumber = regexp.MustCompile(`^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$`)

// release returns the values of raw that fields ask for, and nothing else of what a sensor read: at
// most maxFields fields, scalars only (bool, number, text cut to maxTextRunes), each under the field
// as asked. A field is a path of keys joined by "."; a key that holds a "." itself is found too. A
// field that names no scalar (missing, null, a list, an object, a number that is no JSON number) is
// left out, as is everything without fields.
func release(raw map[string]any, fields []string) map[string]any {
	values := map[string]any{}
	seen := map[string]bool{}
	for _, field := range fields {
		if len(seen) == maxFields {
			break
		}
		if seen[field] {
			continue
		}
		seen[field] = true
		if v, ok := scalar(lookup(raw, field)); ok {
			values[field] = v
		}
	}
	return values
}

// lookup returns the value at path in m: the whole path as one key first, then the key up to the
// first "." and the rest of the path in the object below it.
func lookup(m map[string]any, path string) any {
	if v, ok := m[path]; ok {
		return v
	}
	key, rest, ok := strings.Cut(path, ".")
	if !ok {
		return nil
	}
	below, isMap := m[key].(map[string]any)
	if !isMap {
		return nil
	}
	return lookup(below, rest)
}

// scalar returns v in the form the report carries, if it is a scalar.
func scalar(v any) (any, bool) {
	switch x := v.(type) {
	case bool:
		return x, true
	case string:
		return cleanText(x), true
	case int, int8, int16, int32, int64, uint, uint8, uint16, uint32, uint64:
		return x, true
	case float32:
		return x, finite(float64(x))
	case float64:
		return x, finite(x)
	case json.Number:
		return x, jsonNumber.MatchString(string(x))
	}
	return nil, false
}

// finite says whether f can be written as JSON: NaN and the infinities cannot, and json.Marshal
// would fail the whole report on them.
func finite(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0)
}

// cleanText makes a text value fit the report (cutRunes).
func cleanText(s string) string {
	return cutRunes(s, maxTextRunes)
}
