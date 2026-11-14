// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"errors"
	"fmt"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// The Windows views read only through fixed queries from this package: a WMI class with
// the properties of a Go struct, or an event filter by channel, source, IDs and level. No
// query text comes from the server, and no WMI method is ever called.

var (
	wmiNamespaceRe = regexp.MustCompile(`^root(\\[A-Za-z0-9_]{1,64}){0,4}$`)
	wmiIdentRe     = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,63}$`)
	// A where clause compares properties with numbers or quoted words, nothing more.
	wmiWhereRe = regexp.MustCompile(`^[A-Za-z0-9_ =<>']{0,200}$`)
	// Channel and provider names: letters, digits, blank, dash, dot, slash, underscore, and the
	// dollar of a named SQL Server instance (MSSQL$<instance>).
	eventNameRe = regexp.MustCompile(`^[A-Za-z0-9 ._/$-]{1,128}$`)
)

// wmiQuery is one fixed WMI read. The properties are the field names of the struct the
// caller reads into, so the query asks for exactly what the view keeps.
type wmiQuery struct {
	namespace string
	class     string
	where     string
}

// wql builds the query for dst, a pointer to a slice of structs.
func (q wmiQuery) wql(dst any) (string, error) {
	if !wmiNamespaceRe.MatchString(q.namespace) {
		return "", fmt.Errorf("wmi: namespace %q", q.namespace)
	}
	if !wmiIdentRe.MatchString(q.class) {
		return "", fmt.Errorf("wmi: class %q", q.class)
	}
	if !wmiWhereRe.MatchString(q.where) || strings.Count(q.where, "'")%2 != 0 {
		return "", fmt.Errorf("wmi: where %q", q.where)
	}
	t := reflect.TypeOf(dst)
	if t == nil || t.Kind() != reflect.Pointer || t.Elem().Kind() != reflect.Slice ||
		t.Elem().Elem().Kind() != reflect.Struct {
		return "", errors.New("wmi: dst must point to a slice of structs")
	}
	row := t.Elem().Elem()
	props := make([]string, 0, row.NumField())
	for i := range row.NumField() {
		f := row.Field(i)
		if !f.IsExported() {
			continue
		}
		if !wmiIdentRe.MatchString(f.Name) {
			return "", fmt.Errorf("wmi: property %q", f.Name)
		}
		props = append(props, f.Name)
	}
	if len(props) == 0 {
		return "", errors.New("wmi: no properties")
	}
	s := "SELECT " + strings.Join(props, ", ") + " FROM " + q.class
	if q.where != "" {
		s += " WHERE " + q.where
	}
	return s, nil
}

// eventQuery selects events of one channel by their system values only.
type eventQuery struct {
	channel  string
	provider string        // empty: any source
	ids      []uint16      // empty: any ID
	levels   []uint8       // empty: any level (1 critical, 2 error, 3 warning, 4 information)
	within   time.Duration // zero: no time limit
}

// xpath builds the structured query filter of the Windows event log.
func (q eventQuery) xpath() (string, error) {
	if !eventNameRe.MatchString(q.channel) {
		return "", fmt.Errorf("events: channel %q", q.channel)
	}
	var conds []string
	if q.provider != "" {
		if !eventNameRe.MatchString(q.provider) {
			return "", fmt.Errorf("events: provider %q", q.provider)
		}
		conds = append(conds, "Provider[@Name='"+q.provider+"']")
	}
	if len(q.ids) > 0 {
		alt := make([]string, len(q.ids))
		for i, id := range q.ids {
			alt[i] = "EventID=" + strconv.Itoa(int(id))
		}
		conds = append(conds, "("+strings.Join(alt, " or ")+")")
	}
	if len(q.levels) > 0 {
		alt := make([]string, len(q.levels))
		for i, l := range q.levels {
			if l > 5 {
				return "", fmt.Errorf("events: level %d", l)
			}
			alt[i] = "Level=" + strconv.Itoa(int(l))
		}
		conds = append(conds, "("+strings.Join(alt, " or ")+")")
	}
	if q.within < 0 {
		return "", fmt.Errorf("events: within %s", q.within)
	}
	if q.within > 0 {
		conds = append(conds, "TimeCreated[timediff(@SystemTime) <= "+strconv.FormatInt(q.within.Milliseconds(), 10)+"]")
	}
	if len(conds) == 0 {
		return "*", nil
	}
	return "*[System[" + strings.Join(conds, " and ") + "]]", nil
}
