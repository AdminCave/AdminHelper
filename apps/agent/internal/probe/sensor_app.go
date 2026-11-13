// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"maps"
	"slices"
)

func init() {
	sensors["app"] = appSensor
}

// appView is one view of the app sensor: the kinds of target it is bound to and what reads it.
type appView struct {
	kinds []string
	read  func(ctx context.Context, t Target) (map[string]any, error)
}

// The kinds of target of the views: most read one application installed as a unit or running in a
// container; the certificates of a reverse proxy are read in either.
var (
	unitKinds      = []string{kindUnit}
	containerKinds = []string{kindContainer}
	eitherKinds    = []string{kindUnit, kindContainer}
)

// appViews are the views of the app sensor. Each reads the inside of one application on this host,
// read only: files, the application's API on its own port, its local socket, or a read command of
// the application with fixed arguments, started through the allowlist (runTool). The server names a
// view, never a path, a command or a query.
var appViews = map[string]appView{
	"apcupsd":           {unitKinds, apcupsd},
	"bbb_meetings":      {unitKinds, bbbMeetings},
	"bbb_recordings":    {unitKinds, bbbRecordings},
	"bind_status":       {unitKinds, bindStatus},
	"caddy_certs":       {eitherKinds, caddyCerts},
	"caddy_upstreams":   {unitKinds, caddyUpstreams},
	"chrony_tracking":   {unitKinds, chronyTracking},
	"crowdsec_bouncers": {unitKinds, crowdsecBouncers},
	"dnsmasq_leases":    {unitKinds, dnsmasqLeaseView},
	"fail2ban":          {unitKinds, fail2ban},
	"kea_pools":         {unitKinds, keaPools},
	"keepalived_vips":   {unitKinds, keepalivedVIPs},
	"ldap_replication":  {unitKinds, ldapReplication},
	"npm_certs":         {containerKinds, npmCerts},
	"ntpsec_status":     {unitKinds, ntpsecStatus},
	"nut_ups":           {unitKinds, nutUPS},
	"openvpn_status":    {unitKinds, openvpnStatus},
	"pve_cluster":       {unitKinds, pveCluster},
	"pve_jobs":          {unitKinds, pveJobs},
	"pve_updates":       {unitKinds, pveUpdates},
	"tailscale_status":  {unitKinds, tailscaleStatus},
	"traefik_certs":     {eitherKinds, traefikCerts},
	"unbound_stats":     {unitKinds, unboundStats},
	"wg_peers":          {unitKinds, wgPeers},
	"wordpress_version": {containerKinds, wordpressVersion},
}

// appSensor reads the view the probe names of the application its target belongs to.
func appSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", slices.Sorted(maps.Keys(appViews))...)
	if err != nil {
		return nil, err
	}
	v := appViews[view]
	t, err := targetOf(p, v.kinds...)
	if err != nil {
		return nil, err
	}
	return v.read(ctx, t)
}
