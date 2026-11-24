// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"reflect"
	"testing"
)

// TestSystemStateEmptyCountsEveryField sets each field alone: empty() has to see it, so a field
// added to SystemState without a line in empty() turns this red instead of vanishing from the report.
func TestSystemStateEmptyCountsEveryField(t *testing.T) {
	if !(*SystemState)(nil).empty() || !(&SystemState{}).empty() {
		t.Fatal("a nil or zero SystemState must be empty")
	}
	typ := reflect.TypeFor[SystemState]()
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)
		s := &SystemState{}
		v := reflect.ValueOf(s).Elem().Field(i)
		switch v.Kind() {
		case reflect.Pointer:
			v.Set(reflect.New(v.Type().Elem()))
		case reflect.Slice:
			v.Set(reflect.MakeSlice(v.Type(), 1, 1))
		default:
			t.Fatalf("%s: kind %s not handled by this test", field.Name, v.Kind())
		}
		if s.empty() {
			t.Errorf("%s set, but empty() reports nothing measured", field.Name)
		}
	}
}
