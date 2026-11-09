// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/probe"
)

// planTimeout is the client timeout of the plan request, the same as the push's.
const planTimeout = 15 * time.Second

// The bounds the agent holds every plan to, whatever the monitoring service sent.
const (
	supportedPlanVersion = 1
	maxPlanProbes        = 256
	// minProbeIntervalS: a probe never runs more often than the agent does, every 5 min.
	minProbeIntervalS    = 300
	defaultProbeTimeoutS = 10
	maxProbeTimeoutS     = 30
	probeDueSlack        = 60 * time.Second
)

// probeIDPattern is what a probe id (the check's id, a key of the report's probes block) may hold.
var probeIDPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

// runProbe runs one probe; a seam for the tests.
var runProbe = probe.Run

// currentPlan fetches this host's plan and keeps it in planPath. A plan that cannot be fetched (the
// monitoring service is down, an older one without the route answers 404) or that the agent does not
// understand leaves the saved one in force; without a saved plan no probe runs.
func currentPlan(ctx context.Context, cfg *config.MonitorConfig, planPath string) probe.Plan {
	body, err := fetchPlan(ctx, cfg)
	if err != nil {
		logger.Infof("plan not fetched, the saved plan stays in force: %v", err)
		return loadPlan(planPath)
	}
	plan, err := parsePlan(body)
	if err != nil {
		logger.Warnf("plan refused, the saved plan stays in force: %v", err)
		return loadPlan(planPath)
	}
	if data, err := json.Marshal(plan); err != nil {
		logger.Warnf("saving the plan failed: %v", err)
	} else if err := config.WriteFile(planPath, data, 0600); err != nil {
		logger.Warnf("saving the plan failed: %v", err)
	}
	return plan
}

// fetchPlan GETs the plan with the agent's key over the client the push uses.
func fetchPlan(ctx context.Context, cfg *config.MonitorConfig) ([]byte, error) {
	endpoint := fmt.Sprintf("%s/agent/%s/plan", cfg.MonitorURL, url.PathEscape(cfg.ServerID))
	client, err := enroll.ServerClient(config.AgentPkiDir(), cfg.CACert, cfg.Insecure, planTimeout)
	if err != nil {
		return nil, err
	}
	defer client.CloseIdleConnections()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", cfg.APIKey)
	return httpclient.Do(client, req)
}

// loadPlan reads the saved plan; a missing or broken one is the empty plan.
func loadPlan(path string) probe.Plan {
	data, err := os.ReadFile(path)
	if err != nil {
		return probe.Plan{PlanVersion: supportedPlanVersion}
	}
	plan, err := parsePlan(data)
	if err != nil {
		logger.Warnf("the saved plan is unusable, no probe runs: %v", err)
		return probe.Plan{PlanVersion: supportedPlanVersion}
	}
	return plan
}

// parsePlan decodes a plan and holds it to the agent's bounds: a probe without a usable id (it keys the
// result) or past the first maxPlanProbes is left out, its interval is at least minProbeIntervalS and its
// timeout between 1 and maxProbeTimeoutS seconds (none: defaultProbeTimeoutS).
func parsePlan(data []byte) (probe.Plan, error) {
	var plan probe.Plan
	if err := json.Unmarshal(data, &plan); err != nil {
		return probe.Plan{}, fmt.Errorf("not a plan: %w", err)
	}
	if plan.PlanVersion != supportedPlanVersion {
		return probe.Plan{}, fmt.Errorf("plan_version %d, this agent knows %d", plan.PlanVersion, supportedPlanVersion)
	}
	seen := map[string]bool{}
	probes := make([]probe.Probe, 0, len(plan.Probes))
	left := 0
	for _, p := range plan.Probes {
		if !probeIDPattern.MatchString(p.ID) || seen[p.ID] || len(probes) == maxPlanProbes {
			left++
			continue
		}
		seen[p.ID] = true
		p.IntervalS = max(p.IntervalS, minProbeIntervalS)
		switch {
		case p.TimeoutS <= 0:
			p.TimeoutS = defaultProbeTimeoutS
		case p.TimeoutS > maxProbeTimeoutS:
			p.TimeoutS = maxProbeTimeoutS
		}
		probes = append(probes, p)
	}
	if left > 0 {
		logger.Warnf("plan: %d probes left out (no usable or a repeated id, or more than %d)", left, maxPlanProbes)
	}
	plan.Probes = probes
	return plan, nil
}

// runDueProbes runs those of probes that are due, oldest result first, in what is left of ctx. It
// returns the last result of every one of probes (a result of a probe no longer among them is dropped)
// and how many ran. A probe starts only while ctx leaves it its whole timeout, so the push keeps its
// time; the others stay due for the next run.
func runDueProbes(ctx context.Context, probes []probe.Probe, last probe.Results, now time.Time) (probe.Results, int) {
	next := probe.Results{}
	for _, p := range probes {
		if res, ok := last[p.ID]; ok {
			next[p.ID] = res
		}
	}
	due := make([]probe.Probe, 0, len(probes))
	for _, p := range probes {
		if res, ok := next[p.ID]; !ok || probeDue(p, res, now) {
			due = append(due, p)
		}
	}
	sort.SliceStable(due, func(i, j int) bool {
		return lastRun(next, due[i].ID) < lastRun(next, due[j].ID)
	})

	ran, postponed := 0, 0
	for i, p := range due {
		if ctx.Err() != nil {
			postponed += len(due) - i
			break
		}
		if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) < time.Duration(p.TimeoutS)*time.Second {
			postponed++
			continue
		}
		res := runProbe(ctx, p, time.Now())
		if ctx.Err() != nil {
			// The run ended under the probe: its last result stays, and it is due again next run.
			postponed += len(due) - i
			break
		}
		next[p.ID] = res
		ran++
	}
	if postponed > 0 {
		logger.Warnf("%d due probes postponed to the next run: this run's time is used up", postponed)
	}
	return next, ran
}

// probeDue says whether p, last run as res, is due at now. The slack keeps the agent's own jitter (the
// timer's random delay, collectors that take longer one run than the next) from pushing a probe whose
// interval is one agent run to every other run. A result from the future (the clock went back) is due.
func probeDue(p probe.Probe, res probe.Result, now time.Time) bool {
	age := now.Sub(time.Unix(res.TS, 0))
	return age < 0 || age >= time.Duration(p.IntervalS)*time.Second-probeDueSlack
}

// lastRun is when the probe id last ran, 0 for never.
func lastRun(results probe.Results, id string) int64 {
	if res, ok := results[id]; ok {
		return res.TS
	}
	return 0
}
