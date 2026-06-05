// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"github.com/shirou/gopsutil/v4/sensors"
)

// TempInfo holds the metrics of a temperature sensor.
type TempInfo struct {
	Sensor   string  `json:"sensor"`
	TempC    float64 `json:"temp_c"`
	High     float64 `json:"high"`
	Critical float64 `json:"critical"`
}

// collectTemperatures reads all available temperature sensors via gopsutil.
// On VMs without hwmon sensors, nil is returned (no error).
func collectTemperatures() []TempInfo {
	temps, err := sensors.SensorsTemperatures()
	if err != nil || len(temps) == 0 {
		return nil
	}

	var result []TempInfo
	for _, t := range temps {
		if t.Temperature <= 0 {
			continue
		}
		result = append(result, TempInfo{
			Sensor:   t.SensorKey,
			TempC:    round1(t.Temperature),
			High:     round1(t.High),
			Critical: round1(t.Critical),
		})
	}

	if len(result) == 0 {
		return nil
	}
	return result
}
