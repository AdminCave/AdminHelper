// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"errors"
	"strconv"
	"time"
)

const (
	// wpCronMaxBytes caps the option cron the agent reads; a site with thousands of events stays far below.
	wpCronMaxBytes = 1 << 20
	// wpCronMaxDepth and wpCronMaxValues bound the parse of the option: an event nests four arrays deep, its
	// arguments may nest further.
	wpCronMaxDepth  = 32
	wpCronMaxValues = 200000
	// wpCronLate is how long an event may be due before it counts as overdue: WP-Cron runs due events on a
	// later request, so a few minutes are normal.
	wpCronLate = 10 * time.Minute
)

// errPHPForm is the error of an option not in the form of PHP's serialize(); it quotes nothing of the option.
var errPHPForm = errors.New("the option is not in the form of PHP's serialize()")

// phpValue is a value of PHP's serialize(): kind is its tag (N, b, i, d, s, a or O); num holds an int or a
// bool, str a string, items the pairs of an array or the properties of an object.
type phpValue struct {
	kind  byte
	num   int64
	str   string
	items []phpItem
}

type phpItem struct{ key, val phpValue }

type phpParser struct {
	data   []byte
	pos    int
	values int
}

// parsePHP parses data, the whole of one value of serialize(). It takes the tags WordPress writes into its
// options (no references, no custom serialization) and fails on anything else.
func parsePHP(data []byte) (phpValue, error) {
	p := &phpParser{data: data}
	v, err := p.value(0)
	if err != nil {
		return phpValue{}, err
	}
	if p.pos != len(p.data) {
		return phpValue{}, errPHPForm
	}
	return v, nil
}

func (p *phpParser) value(depth int) (phpValue, error) {
	p.values++
	if depth > wpCronMaxDepth || p.values > wpCronMaxValues || p.pos >= len(p.data) {
		return phpValue{}, errPHPForm
	}
	v := phpValue{kind: p.data[p.pos]}
	p.pos++
	if v.kind == 'N' {
		return v, p.expect(";")
	}
	if err := p.expect(":"); err != nil {
		return phpValue{}, err
	}
	var err error
	switch v.kind {
	case 'b':
		if v.num, err = p.integer(';'); err == nil && v.num != 0 && v.num != 1 {
			err = errPHPForm
		}
	case 'i':
		v.num, err = p.integer(';')
	case 'd':
		err = p.float()
	case 's':
		if v.str, err = p.str(); err == nil {
			err = p.expect(";")
		}
	case 'a':
		v.items, err = p.pairs(depth, false)
	case 'O':
		if _, err = p.str(); err == nil {
			if err = p.expect(":"); err == nil {
				v.items, err = p.pairs(depth, true)
			}
		}
	default:
		err = errPHPForm
	}
	if err != nil {
		return phpValue{}, err
	}
	return v, nil
}

// pairs reads `<n>:{` and n pairs of key and value up to `}`; the keys of an array are ints or strings, those
// of an object strings.
func (p *phpParser) pairs(depth int, object bool) ([]phpItem, error) {
	n, err := p.integer(':')
	if err != nil || n < 0 || n > int64(len(p.data)-p.pos) {
		return nil, errPHPForm
	}
	if err := p.expect("{"); err != nil {
		return nil, err
	}
	var items []phpItem
	for range n {
		key, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		if key.kind != 's' && (object || key.kind != 'i') {
			return nil, errPHPForm
		}
		val, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		items = append(items, phpItem{key, val})
	}
	return items, p.expect("}")
}

// str reads `<len>:"<len bytes>"`.
func (p *phpParser) str() (string, error) {
	n, err := p.integer(':')
	if err != nil || n < 0 || n > int64(len(p.data)-p.pos) {
		return "", errPHPForm
	}
	if err := p.expect(`"`); err != nil {
		return "", err
	}
	if int64(len(p.data)-p.pos) < n {
		return "", errPHPForm
	}
	s := string(p.data[p.pos : p.pos+int(n)])
	p.pos += int(n)
	return s, p.expect(`"`)
}

// integer reads a decimal int of at most 19 digits, an optional '-' before it, and the byte end after it.
func (p *phpParser) integer(end byte) (int64, error) {
	start := p.pos
	if p.pos < len(p.data) && p.data[p.pos] == '-' {
		p.pos++
	}
	digits := p.pos
	for p.pos < len(p.data) && p.pos-digits < 20 && p.data[p.pos] >= '0' && p.data[p.pos] <= '9' {
		p.pos++
	}
	if p.pos == digits || p.pos >= len(p.data) || p.data[p.pos] != end {
		return 0, errPHPForm
	}
	n, err := strconv.ParseInt(string(p.data[start:p.pos]), 10, 64)
	if err != nil {
		return 0, errPHPForm
	}
	p.pos++
	return n, nil
}

// float skips a float up to its ';': digits, sign, point, exponent, or PHP's INF and NAN.
func (p *phpParser) float() error {
	start := p.pos
	for p.pos < len(p.data) && p.pos-start <= 64 && p.data[p.pos] != ';' {
		switch c := p.data[p.pos]; {
		case c >= '0' && c <= '9', c == '-', c == '+', c == '.', c == 'E', c == 'e', c == 'I', c == 'N', c == 'F', c == 'A':
			p.pos++
		default:
			return errPHPForm
		}
	}
	if p.pos == start {
		return errPHPForm
	}
	return p.expect(";")
}

func (p *phpParser) expect(s string) error {
	if len(p.data)-p.pos < len(s) || string(p.data[p.pos:p.pos+len(s)]) != s {
		return errPHPForm
	}
	p.pos += len(s)
	return nil
}

// wpCronCounts counts the events of WordPress's option cron, as _get_cron_array() reads it: an array of
// timestamps, each an array of hooks, each an array of events by the hash of their arguments; the key
// version and any other string key are no timestamp. It returns events (all of them), overdue (those due
// for longer than wpCronLate at now) and oldest_overdue_s (how long the oldest overdue event has been due,
// 0 without one) and nothing else of the option.
func wpCronCounts(data []byte, now time.Time) (map[string]any, error) {
	if len(data) > wpCronMaxBytes {
		return nil, errPHPForm
	}
	v, err := parsePHP(data)
	if err != nil {
		return nil, err
	}
	if v.kind != 'a' {
		return nil, errPHPForm
	}
	late := now.Add(-wpCronLate).Unix()
	var events, overdue, oldest int64
	for _, ts := range v.items {
		if ts.key.kind != 'i' {
			continue
		}
		if ts.val.kind != 'a' {
			return nil, errPHPForm
		}
		for _, hook := range ts.val.items {
			if hook.val.kind != 'a' {
				return nil, errPHPForm
			}
			n := int64(len(hook.val.items))
			events += n
			if n > 0 && ts.key.num < late {
				overdue += n
				oldest = max(oldest, now.Unix()-ts.key.num)
			}
		}
	}
	return map[string]any{"events": events, "overdue": overdue, "oldest_overdue_s": oldest}, nil
}
