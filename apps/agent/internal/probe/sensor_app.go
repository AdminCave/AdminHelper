// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"fmt"
	"maps"
	"slices"
	"strings"

	"adminhelper-agent/internal/allowlist"
)

func init() {
	sensors["app"] = appSensor
}

// appView is one view of the app sensor: the kinds of target it is bound to and what reads it. A view
// that reads with a credential stored on this host names the uses it takes and reads with readCred.
type appView struct {
	kinds    []string
	read     func(ctx context.Context, t Target) (map[string]any, error)
	uses     []string
	readCred func(ctx context.Context, t Target, c appCredential) (map[string]any, error)
}

// appCredential is the credential a probe hands to its view: how it is presented (use, "" without
// one) and the secret.
type appCredential struct {
	use, secret string
}

// runToolEnv starts a read command with a credential in its environment (passwordEnv); tests stand in
// their own.
var runToolEnv = allowlist.RunEnv

// passwordEnv returns the environment entry name=secret for a credential of use password, nil
// without a credential. The secret goes to the one command it is handed to and in no argument, where
// every user of the host could read it (/proc/<pid>/cmdline); no error quotes it.
func passwordEnv(c appCredential, name string) ([]string, error) {
	switch {
	case c.use == "":
		return nil, nil
	case c.use != usePassword:
		return nil, fmt.Errorf("%w: a credential for %q cannot be handed to a command", ErrInvalid, c.use)
	case c.secret == "" || strings.ContainsRune(c.secret, 0):
		return nil, fmt.Errorf("%w: a password must be non-empty and hold no NUL byte", ErrInvalid)
	}
	return []string{name + "=" + c.secret}, nil
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
	"apcupsd":           {kinds: unitKinds, read: apcupsd},
	"apache_status":     {kinds: unitKinds, read: apacheStatus},
	"bbb_meetings":      {kinds: unitKinds, read: bbbMeetings},
	"bbb_recordings":    {kinds: unitKinds, read: bbbRecordings},
	"bind_status":       {kinds: unitKinds, read: bindStatus},
	"caddy_certs":       {kinds: eitherKinds, read: caddyCerts},
	"caddy_upstreams":   {kinds: unitKinds, read: caddyUpstreams},
	"ceph_health":       {kinds: unitKinds, read: cephHealth},
	"chrony_tracking":   {kinds: unitKinds, read: chronyTracking},
	"crowdsec_bouncers": {kinds: unitKinds, read: crowdsecBouncers},
	"dnsmasq_leases":    {kinds: unitKinds, read: dnsmasqLeaseView},
	"fail2ban":          {kinds: unitKinds, read: fail2ban},
	"haproxy_servers":   {kinds: unitKinds, read: haproxyServers},
	"kea_pools":         {kinds: unitKinds, read: keaPools},
	"keepalived_vips":   {kinds: unitKinds, read: keepalivedVIPs},
	"ldap_replication":  {kinds: unitKinds, read: ldapReplication},
	"npm_certs":         {kinds: containerKinds, read: npmCerts},
	"nginx_status":      {kinds: unitKinds, read: nginxStatus},
	"ntpsec_status":     {kinds: unitKinds, read: ntpsecStatus},
	"nut_ups":           {kinds: unitKinds, read: nutUPS},
	"openvpn_status":    {kinds: unitKinds, read: openvpnStatus},
	"pbs_status":        {kinds: unitKinds, read: pbsStatus},
	"pve_cluster":       {kinds: unitKinds, read: pveCluster},
	"pve_jobs":          {kinds: unitKinds, read: pveJobs},
	"pve_updates":       {kinds: unitKinds, read: pveUpdates},
	"tailscale_status":  {kinds: unitKinds, read: tailscaleStatus},
	"traefik_certs":     {kinds: eitherKinds, read: traefikCerts},
	"unbound_stats":     {kinds: unitKinds, read: unboundStats},
	"wg_peers":          {kinds: unitKinds, read: wgPeers},
	"web_config":        {kinds: unitKinds, read: webConfig},
	"wordpress_version": {kinds: containerKinds, read: wordpressVersion},
}

// appSensor reads the view the probe names of the application its target belongs to. A credential
// goes only to a view that takes its use; any other view refuses it.
func appSensor(ctx context.Context, p Probe, secret string) (map[string]any, error) {
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", slices.Sorted(maps.Keys(appViews))...)
	if err != nil {
		return nil, err
	}
	v := appViews[view]
	use, err := credentialUse(p, v.uses...)
	if err != nil {
		return nil, err
	}
	t, err := targetOf(p, v.kinds...)
	if err != nil {
		return nil, err
	}
	if v.readCred != nil {
		return v.readCred(ctx, t, appCredential{use: use, secret: secret})
	}
	return v.read(ctx, t)
}
