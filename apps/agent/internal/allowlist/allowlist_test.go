// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package allowlist

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"
)

const cursor = "s=0123456789abcdef0123456789abcdef;i=1a2b;b=fedcba9876543210fedcba9876543210;m=3c4d;t=5e6f;x=7a8b"

// TestAllowlistTakesEveryProbeAndDiscoveryCall runs the calls of the sensors (probe) and of discovery
// through the list, with the variable parts in the forms they come in; the collectors' calls are
// monitor's test, and the stubs of probe and discovery check every call their tests make.
func TestAllowlistTakesEveryProbeAndDiscoveryCall(t *testing.T) {
	head := []string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor"}
	journal := func(rest ...string) []string { return append(append([]string{}, head...), rest...) }
	calls := [][]string{
		journal("--priority=3", "--since=-60s"),
		journal("--priority=0", "--after-cursor="+cursor),
		journal("--priority=7", "--unit=nginx.service", "--since=-300s"),
		journal("--priority=3", "--unit=getty@tty1.service", "--after-cursor="+cursor, "--", "_COMM=sshd"),
		journal("--priority=4", "--since=-60s", "--", "SYSLOG_IDENTIFIER=postfix/smtpd"),
		journal("--priority=4", "--unit=-.slice", "--since=-60s", "--", "CONTAINER_NAME=web-1"),
		{"systemctl", "show", "-p", "LoadState,ActiveState,SubState,NRestarts,ActiveEnterTimestampMonotonic,Result,ExecMainCode,ExecMainStatus,ExecMainExitTimestampMonotonic", "--", "nginx.service"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "-.slice"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", `systemd-fsck@dev-disk-by\x2duuid-1a2b.service`},
		{"docker", "inspect", "--type", "container", "--", "web_1.prod"},
		{"docker", "inspect", "--type", "container", "--", "0123456789ab"},
		{"systemctl", "list-units", "--type=service", "--all", "--full", "--no-legend", "--plain", "--no-pager"},
		{"docker", "ps", "--all", "--quiet", "--no-trunc"},
		{"docker", "inspect", "--type", "container", strings.Repeat("a", 64), strings.Repeat("0", 64)},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "nginx", "libc6", "g++-12"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "nginx", "postgresql16-server"},
		{"/usr/bin/sockstat", "-46", "-l", "-n", "-q", "-w", "-P", "tcp"},
		{"/usr/sbin/service", "nginx", "onestatus"},
		{"/usr/local/sbin/configctl", "interface", "gateways", "status"},
		{"/usr/local/sbin/configctl", "firmware", "product"},
	}
	for _, args := range mariadbCalls {
		calls = append(calls, append([]string{"mariadb"}, args...), append([]string{"mysql"}, args...))
	}
	for _, args := range postgresCalls {
		calls = append(calls, append([]string{"runuser"}, args...))
	}
	for _, user := range []string{"web", "node_1", "_svc", "r", "ro", "roo", "rooter", "rob", "rot", "roox", "deploy-2"} {
		calls = append(calls, []string{"runuser", "-u", user, "--", "pm2", "jlist"})
	}
	for _, call := range calls {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	if len(journalCalls) != 8 || len(mariadbCalls) != 6 || len(postgresCalls) != 6 {
		t.Errorf("%d journalctl, %d MariaDB, %d PostgreSQL calls; want 8, 6, 6",
			len(journalCalls), len(mariadbCalls), len(postgresCalls))
	}
}

// TestAllowlistRefusesTheProbeAndDiscoveryTraps is the negative test: calls that bend an allowed one
// of the sensors or of discovery into another output, another user, another query or an option.
func TestAllowlistRefusesTheProbeAndDiscoveryTraps(t *testing.T) {
	head := []string{"journalctl", "--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor"}
	journal := func(rest ...string) []string { return append(append([]string{}, head...), rest...) }
	sql := mariadbCalls[0]
	pg := postgresCalls[0]
	calls := [][]string{
		{"journalctl", "--no-pager", "--quiet", "--output=json", "--show-cursor", "--priority=3", "--since=-60s"},
		journal("--priority=3"),
		journal("--priority=8", "--since=-60s"),
		journal("--priority=3", "--since=-60s", "--", "MESSAGE=password"),
		journal("--priority=3", "--since=-60s", "--", "--help"),
		journal("--priority=3", "--since=-60s", "_COMM=sshd"),
		journal("--priority=3", "--after-cursor=x y"),
		journal("--priority=3", "--unit=*", "--since=-60s"),
		journal("--priority=3", "--since=-60s", "--file=/etc/shadow"),
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "--help"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "nginx"},
		{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "a", "b"},
		{"systemctl", "show", "-p", "LoadState,ExecStart", "--", "nginx"},
		{"docker", "inspect", "--type", "container", "--", "-f"},
		{"docker", "inspect", "--type", "container", "--", "../x"},
		{"docker", "inspect", "--type", "container", "web"},
		{"docker", "ps", "--all", "--quiet"},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--"},
		{"dpkg-query", "--show", `--showformat=${Conffiles}\n`, "--", "nginx"},
		{"dpkg-query", "--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "-x"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "-e"},
		{"rpm", "--query", `--queryformat=%{NAME}\n`, "--", "nginx"},
		{"rpm", "--erase", "nginx"},
		append([]string{"mariadb"}, append(append([]string{}, sql[:len(sql)-1]...), "--execute=SELECT * FROM mysql.user")...),
		append([]string{"mysql"}, append(append([]string{}, sql...), "--user=root")...),
		append([]string{"runuser"}, append(append([]string{}, pg[:len(pg)-1]...), "--command=SELECT * FROM pg_authid")...),
		append([]string{"runuser", "-u", "root"}, pg[2:]...),
		{"runuser", "-u", "root", "--", "pm2", "jlist"},
		{"runuser", "-u", "Root", "--", "pm2", "jlist"},
		{"runuser", "-u", "-web", "--", "pm2", "jlist"},
		{"runuser", "-u", "web", "--", "pm2", "restart", "all"},
		{"runuser", "-u", "web", "--", "pm2", "reload", "all"},
		{"runuser", "-u", "web", "--", "pm2", "delete", "all"},
		{"runuser", "-u", "web", "--", "pm2", "flush"},
		{"runuser", "-u", "web", "--", "pm2", "jlist", "--silent"},
		{"runuser", "-u", "web", "--", "pm2", "prettylist"},
		{"runuser", "-u", "web", "pm2", "jlist"},
		{"runuser", "-u", "web", "--", "psql", "--command=SELECT 1"},
		{"runuser", "-u", "postgres", "--", "pm2", "jlist", "x"},
		{"pm2", "jlist"},
		{"psql", "--command=SELECT 1"},
		{"sockstat", "-46", "-l", "-n", "-q", "-w", "-P", "tcp", "-j", "web"},
		{"sockstat", "-46", "-c", "-n", "-q", "-w", "-P", "tcp"},
		{"sockstat", "-46", "-l", "-n", "-q", "-w", "-P", "tcp", "-p", "22"},
		{"sockstat", "-u", "-l", "-n", "-q", "-w"},
		{"sockstat"},
		{"service", "nginx", "onestart"},
		{"service", "-nginx", "onestatus"},
		{"configctl", "firmware", "update"},
		{"configctl", "firmware", "product", "now"},
		{"configctl", "service", "restart", "all"},
		{"configctl"},
		{"sh", "-c", "true"},
	}
	for _, call := range calls {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistOOMJournal: the system state's journalctl call after an OOM kill takes a number of
// seconds and nothing else. The traps bend it into another output, the whole journal, other
// priorities, an option or another time in the seconds field, another file or a match, or the log
// sensor's head with the kernel messages.
func TestAllowlistOOMJournal(t *testing.T) {
	oom := func(since string) []string {
		return []string{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--priority=3", since}
	}
	for _, since := range []string{"--since=-1s", "--since=-301s", "--since=-3600s"} {
		if !Allowed("journalctl", oom(since)) {
			t.Errorf("refused: %q", oom(since))
		}
	}
	for _, args := range [][]string{
		{"--no-pager", "--quiet", "--dmesg", "--output=json", "--priority=3", "--since=-60s"},
		{"--no-pager", "--quiet", "--dmesg", "--output=verbose", "--priority=3", "--since=-60s"},
		{"--no-pager", "--quiet", "--output=cat", "--priority=3", "--since=-60s"},
		{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--priority=7", "--since=-60s"},
		{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--since=-60s"},
		oom("--since=--help"),
		oom("--since=---helps"),
		oom("--since=-60"),
		oom("--since=yesterday"),
		oom("--since=-1x2s"),
		append(oom("--since=-60s"), "--file=/etc/shadow"),
		append(oom("--since=-60s"), "--", "_COMM=sshd"),
		{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--priority=3", "--after-cursor=" + cursor},
		{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--output-fields=PRIORITY", "--show-cursor", "--priority=3", "--since=-60s"},
		{"--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor", "--priority=3", "--since=-60s", "--dmesg"},
	} {
		if Allowed("journalctl", args) {
			t.Errorf("allowed: journalctl %q", args)
		}
	}
}

// TestAllowlistProxmoxBackupDetails: the backup details read the vzdump jobs, the node's last failed
// vzdump task and that task's log, by a UPID in the form PVE writes it. The traps bend them into
// another task type or path, a UPID that leaves its path segment, another limit or filter, a single
// job, or the task list of every type.
func TestAllowlistProxmoxBackupDetails(t *testing.T) {
	tasks := func(node string) []string {
		return []string{"get", "/nodes/" + node + "/tasks", "--typefilter", "vzdump", "--statusfilter", "error", "--limit", "1", "--output-format", "json"}
	}
	taskLog := func(upid string) []string {
		return []string{"get", "/nodes/pve/tasks/" + upid + "/log", "--limit", "10000", "--output-format", "json"}
	}
	for _, args := range [][]string{
		{"get", "/cluster/backup", "--output-format", "json"},
		tasks("pve"),
		tasks("node-2"),
		taskLog("UPID:pve:0000ABCD:0123ABCD5:67890ABC:vzdump:100:root@pam:"),
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump::root@pam:"),
		taskLog("UPID:node-2:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam!backup-tok:"),
	} {
		if !Allowed("pvesh", args) {
			t.Errorf("refused: pvesh %q", args)
		}
	}
	for _, args := range [][]string{
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:qmstart:100:root@pam:"),
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam/../../x:"),
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:abc:root@pam:"),
		taskLog("UPID:pve:0000abcd:0123ABCD:67890ABC:vzdump:100:root@pam:"),
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam"),
		taskLog("UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root pam:"),
		taskLog("UPID:-pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam:"),
		{"get", "/nodes/pve/tasks/UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam:/status", "--output-format", "json"},
		{"get", "/nodes/pve/tasks/UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam:/log", "--limit", "50000", "--output-format", "json"},
		{"get", "/nodes/pve/tasks/UPID:pve:0000ABCD:0123ABCD:67890ABC:vzdump:100:root@pam:/log", "--output-format", "json"},
		{"get", "/nodes/pve/tasks", "--limit", "1", "--output-format", "json"},
		{"get", "/nodes/pve/tasks", "--typefilter", "vzdump", "--errors", "1", "--limit", "1", "--output-format", "json"},
		{"get", "/nodes/pve/tasks", "--typefilter", "qmstart", "--statusfilter", "error", "--limit", "1", "--output-format", "json"},
		{"get", "/nodes/pve/tasks", "--typefilter", "vzdump", "--statusfilter", "error", "--limit", "1000", "--output-format", "json"},
		{"get", "/cluster/backup/backup-1a2b", "--output-format", "json"},
		{"get", "/cluster/backup", "--output-format", "text"},
		{"set", "/cluster/backup", "--output-format", "json"},
	} {
		if Allowed("pvesh", args) {
			t.Errorf("allowed: pvesh %q", args)
		}
	}
}

func TestAllowlistZFSDetails(t *testing.T) {
	for _, args := range [][]string{
		{"list", "-H", "-o", "name,size,alloc,free,cap,health,frag"},
		{"status", "-x"},
		{"status", "-j", "--json-int", "--json-flat-vdevs"},
	} {
		if !Allowed("zpool", args) {
			t.Errorf("refused: zpool %q", args)
		}
	}
	for _, args := range [][]string{
		{"list", "-H", "-o", "name,size,alloc,free,cap,health"},
		{"list", "-H", "-o", "name,size,alloc,free,cap,health,frag,comment"},
		{"list", "-j"},
		{"status", "-j"},
		{"status", "-j", "-v"},
		{"status", "-j", "--json-int", "--json-flat-vdevs", "-v"},
		{"status", "-j", "--json-int", "--json-flat-vdevs", "tank"},
		{"status", "-j", "--json-int", "--json-flat-vdevs", "--json-pool-key-guid"},
		{"status", "-v"},
		{"scrub", "tank"},
	} {
		if Allowed("zpool", args) {
			t.Errorf("allowed: zpool %q", args)
		}
	}
}

// TestAllowlistNetSecurityViews: the app sensor's views of WireGuard, fail2ban, CrowdSec and Tailscale
// read handshake times, keepalive intervals, status counts and the bouncer and node state. The traps
// print the private key or the banned addresses, change bans or the configuration, or probe the
// network.
func TestAllowlistNetSecurityViews(t *testing.T) {
	for _, call := range [][]string{
		{"wg", "show", "all", "latest-handshakes"},
		{"wg", "show", "all", "persistent-keepalive"},
		{"fail2ban-client", "ping"},
		{"fail2ban-client", "status"},
		{"fail2ban-client", "status", "sshd"},
		{"fail2ban-client", "status", "nginx-http-auth"},
		{"/usr/bin/fail2ban-client", "status", "postfix_sasl.2"},
		{"cscli", "bouncers", "list", "-o", "json"},
		{"tailscale", "status", "--json", "--peers=false"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"wg", "show", "all", "dump"},
		{"wg", "show", "wg0", "dump"},
		{"wg", "show", "all", "private-key"},
		{"wg", "show", "all", "preshared-keys"},
		{"wg", "show", "all", "endpoints"},
		{"wg", "show", "wg0", "latest-handshakes"},
		{"wg", "showconf", "wg0"},
		{"wg", "set", "wg0", "peer", "x", "remove"},
		{"wg", "show"},
		{"fail2ban-client", "unban", "--all"},
		{"fail2ban-client", "set", "sshd", "unbanip", "192.0.2.1"},
		{"fail2ban-client", "reload"},
		{"fail2ban-client", "stop"},
		{"fail2ban-client", "status", "--all"},
		{"fail2ban-client", "status", "-d"},
		{"fail2ban-client", "status", "sshd", "extended"},
		{"fail2ban-client", "status", "sshd jail"},
		{"fail2ban-client", "get", "sshd", "banip"},
		{"cscli", "decisions", "add", "--ip", "192.0.2.1"},
		{"cscli", "decisions", "list", "-o", "json"},
		{"cscli", "bouncers", "add", "x"},
		{"cscli", "bouncers", "delete", "x"},
		{"cscli", "bouncers", "list"},
		{"tailscale", "netcheck"},
		{"tailscale", "status", "--json"},
		{"tailscale", "status", "--json", "--peers=false", "--web"},
		{"tailscale", "up"},
		{"tailscale", "down"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistWebViews: the web server views run the configuration tests, the dump of nginx's
// configuration and Apache's list of its files, HAProxy's test only on the file of the packages. The
// traps signal or start the server, or point it at another configuration.
func TestAllowlistWebViews(t *testing.T) {
	for _, call := range [][]string{
		{"nginx", "-t"},
		{"/usr/sbin/nginx", "-T"},
		{"apache2ctl", "-t"},
		{"apache2ctl", "-t", "-D", "DUMP_INCLUDES"},
		{"apachectl", "-t"},
		{"apachectl", "-t", "-D", "DUMP_INCLUDES"},
		{"haproxy", "-c", "-q", "-f", "/etc/haproxy/haproxy.cfg"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"nginx"},
		{"nginx", "-s", "stop"},
		{"nginx", "-s", "reload"},
		{"nginx", "-s", "reopen"},
		{"nginx", "-t", "-c", "/tmp/x.conf"},
		{"nginx", "-T", "-g", "daemon off;"},
		{"nginx", "-t", "-q"},
		{"apache2ctl", "graceful"},
		{"apache2ctl", "restart"},
		{"apache2ctl", "stop"},
		{"apachectl", "-k", "graceful"},
		{"apachectl", "-t", "-D", "DUMP_RUN_CFG"},
		{"apachectl", "-t", "-f", "/tmp/x.conf"},
		{"apache2ctl", "configtest", "-D", "DUMP_INCLUDES"},
		{"haproxy", "-f", "/etc/haproxy/haproxy.cfg"},
		{"haproxy", "-c", "-f", "/etc/haproxy/haproxy.cfg"},
		{"haproxy", "-c", "-q", "-f", "/tmp/x.cfg"},
		{"haproxy", "-f", "/etc/haproxy/haproxy.cfg", "-sf", "1234"},
		{"haproxy", "-c", "-q", "-f", "/etc/haproxy/haproxy.cfg", "-st", "1234"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistDNSAndTimeViews: the app sensor's views of BIND, Unbound, chrony and NTPsec read the
// status, the counters without resetting them, the tracking report and three system variables. The
// traps write the statistics file, reset the counters, step or poll the clock, or read other
// variables.
func TestAllowlistDNSAndTimeViews(t *testing.T) {
	for _, call := range [][]string{
		{"rndc", "status"},
		{"/usr/sbin/rndc", "status"},
		{"unbound-control", "stats_noreset"},
		{"chronyc", "-c", "tracking"},
		{"ntpq", "-c", "rv 0 leap,stratum,offset"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"rndc", "stats"},
		{"rndc", "reload"},
		{"rndc", "flush"},
		{"rndc", "dumpdb"},
		{"rndc", "status", "-x"},
		{"unbound-control", "stats"},
		{"unbound-control", "reload"},
		{"unbound-control", "dump_cache"},
		{"unbound-control", "stats_noreset", "-c", "/tmp/x.conf"},
		{"chronyc", "makestep"},
		{"chronyc", "burst", "4/4"},
		{"chronyc", "-c", "sources"},
		{"chronyc", "tracking"},
		{"chronyc", "-c", "tracking", "makestep"},
		{"ntpq", "-c", "rv"},
		{"ntpq", "-c", "rv 0"},
		{"ntpq", "-c", "rv 0 leap,stratum,offset,clock"},
		{"ntpq", "-c", "peers"},
		{"ntpq", "-c", "rv 0 leap,stratum,offset", "-c", "mrulist"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistHostStorageViews: the host sensor's thin pool view asks lvs for three fields as JSON.
// The traps change an LV or the device mapper, act on an md array, or widen the lvs report.
func TestAllowlistHostStorageViews(t *testing.T) {
	for _, call := range [][]string{
		{"lvs", "--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent"},
		{"/usr/sbin/lvs", "--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"lvs"},
		{"lvs", "--reportformat", "json", "-o", "lv_name,vg_name"},
		{"lvs", "--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent", "--config", "x"},
		{"lvs", "--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent", "vg0"},
		{"lvchange", "-an", "vg0/pool"},
		{"lvextend", "-l", "+100%FREE", "vg0/pool"},
		{"dmsetup", "status"},
		{"dmsetup", "suspend", "vg0-pool"},
		{"mdadm", "--detail", "/dev/md0"},
		{"mdadm", "--action", "check", "/dev/md0"},
		{"mdadm", "/dev/md0", "--fail", "/dev/sda1"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistHostHardwareViews: the host sensor's hardware views ask the controller CLIs for their
// state without a log file and ipmitool for the sensor list from the SDR cache in the state directory.
// The traps start a learn cycle, clear an event log, read or clear the SEL, write a cache elsewhere, or
// read the SDR without the cache.
func TestAllowlistHostHardwareViews(t *testing.T) {
	for _, call := range [][]string{
		{"/opt/MegaRAID/storcli/storcli64", "/call", "show", "all", "J", "nolog"},
		{"/opt/MegaRAID/perccli/perccli64", "/call", "show", "all", "J", "nolog"},
		{"/usr/sbin/ssacli", "ctrl", "all", "show", "status"},
		{"/usr/sbin/ssacli", "ctrl", "all", "show", "config"},
		{"ipmitool", "-S", "/etc/adminhelper/.ipmi-sdr.cache", "sdr", "elist"},
		{"ipmitool", "sdr", "dump", "/etc/adminhelper/.ipmi-sdr.cache.new"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"storcli64", "/call", "show", "all", "J"},
		{"storcli64", "/call", "show", "all"},
		{"storcli64", "/c0/bbu", "start", "learn", "nolog"},
		{"storcli64", "/c0", "delete", "events", "nolog"},
		{"storcli64", "/call", "show", "events", "nolog"},
		{"storcli64", "/call", "set", "alarm=off", "nolog"},
		{"perccli64", "/c0/bbu", "start", "learn"},
		{"storcli2", "/call", "show", "all", "J", "nolog"},
		{"ssacli", "ctrl", "all", "show", "config", "detail"},
		{"ssacli", "ctrl", "slot=0", "modify", "dwc=enable"},
		{"ssacli", "ctrl", "slot=0", "pd", "all", "show", "detail"},
		{"ipmitool", "sel", "clear"},
		{"ipmitool", "sel", "elist"},
		{"ipmitool", "sdr", "elist"},
		{"ipmitool", "-S", "/etc/adminhelper/.ipmi-sdr.cache", "sel", "elist"},
		{"ipmitool", "-S", "/etc/adminhelper/../shadow", "sdr", "elist"},
		{"ipmitool", "sdr", "dump", "/etc/cron.d/x"},
		{"ipmitool", "sdr", "dump", "/etc/../root/.ipmi-sdr.cache.new"},
		{"ipmitool", "sdr", "dump", "relative/.ipmi-sdr.cache.new"},
		{"ipmitool", "chassis", "power", "off"},
		{"ipmitool", "raw", "0x06", "0x01"},
		{"ipmitool", "mc", "reset", "cold"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestAllowlistUPSViews: the UPS views ask the upsd and the apcupsd on localhost for a list and a
// status. The traps command or reconfigure a UPS, shut the clients down, or ask another host.
func TestAllowlistUPSViews(t *testing.T) {
	for _, call := range [][]string{
		{"upsc", "-l", "localhost"},
		{"upsc", "eaton5sc@localhost"},
		{"upsc", "ups_1.rack-a@localhost"},
		{"/usr/bin/upsc", "-l", "localhost"},
		{"apcaccess", "-u", "status"},
		{"/usr/sbin/apcaccess", "-u", "status"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"upscmd", "ups@localhost", "shutdown.return"},
		{"upscmd", "-l", "ups@localhost"},
		{"upsrw", "-s", "ups.delay.shutdown=1", "ups@localhost"},
		{"upsrw", "ups@localhost"},
		{"upsmon", "-c", "fsd"},
		{"upsmon", "-c", "stop"},
		{"upsc", "-l"},
		{"upsc", "-l", "nas.example"},
		{"upsc", "ups@nas.example"},
		{"upsc", "ups@localhost:3494"},
		{"upsc", "ups@other@localhost"},
		{"upsc", "-c", "ups@localhost"},
		{"upsc", "ups@localhost", "ups.status"},
		{"upsc", "-l", "localhost", "extra"},
		{"apcaccess"},
		{"apcaccess", "status"},
		{"apcaccess", "-h", "nas.example:3551", "-u", "status"},
		{"apcaccess", "-f", "/tmp/x.conf", "-u", "status"},
		{"apcaccess", "-u", "status", "nas.example"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

func TestAllowlistPVEViews(t *testing.T) {
	for _, call := range [][]string{
		{"pvesh", "get", "/cluster/status", "--output-format", "json"},
		{"pvesh", "get", "/cluster/ha/status/current", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/replication", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/tasks", "--typefilter", "vzdump", "--limit", "50", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/apt/update", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/subscription", "--output-format", "json"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"pvesh", "create", "/nodes/pve1/apt/update", "--output-format", "json"},
		{"pvesh", "set", "/cluster/ha/status/current", "--output-format", "json"},
		{"pvesh", "delete", "/nodes/pve1/replication", "--output-format", "json"},
		{"pvesh", "create", "/nodes/pve1/subscription", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/storage", "--output-format", "json"},
		{"pvesh", "get", "/cluster/replication", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/tasks", "--typefilter", "vzdump", "--limit", "5000", "--output-format", "json"},
		{"pvesh", "get", "/nodes/pve1/tasks", "--typefilter", "qmstart", "--limit", "50", "--output-format", "json"},
		{"pvesh", "get", "/nodes/../cluster/replication", "--output-format", "json"},
		{"pvesh", "get", "/nodes/-x/apt/update", "--output-format", "json"},
		{"pvesh", "get", "/cluster/status"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

func TestAllowlistPBSCephAndSanoidViews(t *testing.T) {
	for _, call := range [][]string{
		{"proxmox-backup-debug", "api", "get", "/config/datastore", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/status/datastore-usage", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "garbage_collection", "--limit", "50", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "verif", "--limit", "50", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "sync", "--limit", "50", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "prune", "--limit", "50", "--output-format", "json"},
		{"ceph", "health", "-f", "json"},
		{"ceph", "df", "-f", "json"},
		{"sanoid", "--monitor-snapshots"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"proxmox-backup-debug", "api", "set", "/config/datastore", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "create", "/config/datastore", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "delete", "/config/datastore", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/access/users", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--limit", "100", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "backup", "--limit", "50", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/nodes/localhost/tasks", "--typefilter", "prune", "--limit", "100000", "--output-format", "json"},
		{"proxmox-backup-debug", "api", "get", "/config/datastore"},
		{"proxmox-backup-manager", "datastore", "update", "store1", "--maintenance-mode", "offline"},
		{"proxmox-backup-manager", "datastore", "list", "--output-format", "json"},
		{"ceph", "osd", "set", "noout"},
		{"ceph", "config", "set", "global", "mon_allow_pool_delete", "true"},
		{"ceph", "health", "detail", "-f", "json"},
		{"ceph", "df", "detail", "-f", "json"},
		{"ceph", "health"},
		{"sanoid", "--cron"},
		{"sanoid", "--take-snapshots"},
		{"sanoid", "--prune-snapshots"},
		{"sanoid", "--monitor-snapshots", "--configdir", "/tmp/x"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}

// TestNoClassTakesAnOption: no class matches an argument that begins with '-', but unitarg, which takes
// "-" only for the root units and stands right after "--" or behind a literal option.
func TestNoClassTakesAnOption(t *testing.T) {
	for name, class := range Classes() {
		re := regexp.MustCompile("^(?:" + class + ")$")
		for _, arg := range []string{"-", "-x", "--help", "-1", "-.", "-.slice/x", "-x.slice"} {
			if re.MatchString(arg) {
				t.Errorf("class %s takes %q", name, arg)
			}
		}
	}
	unitarg := regexp.MustCompile("^(?:" + classes["unitarg"] + ")$")
	for _, arg := range []string{"-.slice", "-.mount"} {
		if !unitarg.MatchString(arg) {
			t.Errorf("unitarg refuses the root unit %q", arg)
		}
	}
	for _, entries := range commands {
		for _, args := range entries {
			for i, arg := range args {
				if strings.HasPrefix(arg, "<unitarg>") && (arg != "<unitarg>" || i == 0 || args[i-1] != "--") {
					t.Errorf("entry %q has <unitarg> neither right after \"--\" nor behind an option", args)
				}
			}
		}
	}
}

// TestRunRefusesACallOffTheList: a refused call does not start, and its error is ErrNotAllowed.
func TestRunRefusesACallOffTheList(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("starts a shell script")
	}
	marker := filepath.Join(t.TempDir(), "started")
	out, err := Run(context.Background(), time.Minute, "sh", "-c", "touch "+marker)
	if out != nil || !errors.Is(err, ErrNotAllowed) {
		t.Fatalf("Run = %q, %v; want no output and ErrNotAllowed", out, err)
	}
	if _, err := os.Stat(marker); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the refused call started: %v", err)
	}
}

// TestRunStartsAnAllowedCall is the counter-check: an allowed call does start. The command is a script
// named timedatectl, by its absolute path, which counts by its base name.
func TestRunStartsAnAllowedCall(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("starts a shell script")
	}
	tool := filepath.Join(t.TempDir(), "timedatectl")
	if err := os.WriteFile(tool, []byte("#!/bin/sh\necho \"ran $1\"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	out, err := Run(context.Background(), time.Minute, tool, "show")
	if err != nil || string(out) != "ran show\n" {
		t.Errorf("Run = %q, %v; want the script's output", out, err)
	}
}

// TestKeyTakesASlashRootedName: the FreeBSD calls' absolute paths count by their base name on every
// host, Windows included (no volume there); a relative name with a slash stays as it is.
func TestKeyTakesASlashRootedName(t *testing.T) {
	cases := []struct {
		name    string
		windows bool
		want    string
	}{
		{"/usr/sbin/service", false, "service"},
		{"/usr/sbin/service", true, "service"},
		{"/usr/local/sbin/pkg", true, "pkg"},
		{"/bin/freebsd-version", true, "freebsd-version"},
		{"/usr/bin/sockstat", true, "sockstat"},
		{"sbin/service", false, "sbin/service"},
		{"sbin/service", true, "sbin/service"},
	}
	for _, c := range cases {
		if got := Key(c.name, c.windows); got != c.want {
			t.Errorf("Key(%q, %v) = %q, want %q", c.name, c.windows, got, c.want)
		}
	}
	if !Allowed("/usr/sbin/service", []string{"-e"}) || Allowed("sbin/service", []string{"-e"}) {
		t.Error("the list takes a relative service, or refuses /usr/sbin/service -e")
	}
}

// TestClassesIsACopy: what a caller does to the map Classes returns does not change the list.
func TestClassesIsACopy(t *testing.T) {
	c := Classes()
	c["unit"] = ".*"
	if Classes()["unit"] == ".*" {
		t.Error("Classes returned the list's own map")
	}
}

func TestAllowlistBackupViews(t *testing.T) {
	for _, call := range [][]string{
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "hosts"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/BackupPC/bin/BackupPC_serverMesg", "status", "hosts"},
		{"veeamconfig", "session", "list"},
		{"restic", "snapshots", "--json", "--latest", "1", "--no-lock", "--no-cache"},
		{"borg", "list", "--last", "1", "--json", "--bypass-lock"},
		{"kopia", "snapshot", "list", "--json", "-n", "1"},
		{"duplicati-server-util", "health"},
		{"systemctl", "show", "-p", "LoadState,Environment,EnvironmentFiles", "--", "restic-backup.service"},
	} {
		if !Allowed(call[0], call[1:]) {
			t.Errorf("refused: %q", call)
		}
	}
	for _, call := range [][]string{
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "backup", "pc1", "pc1", "backuppc", "1"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "stop", "pc1"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "server", "reload"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "host(pc1)"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "hosts", "x"},
		{"runuser", "-u", "root", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "hosts"},
		{"runuser", "-u", "backuppc", "--", "/tmp/BackupPC_serverMesg", "status", "hosts"},
		{"runuser", "-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_dump", "-f", "pc1"},
		{"/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "hosts"},
		{"BackupPC_serverMesg", "backup", "pc1", "pc1", "backuppc", "1"},
		{"rsnapshot", "alpha"},
		{"rsnapshot", "du"},
		{"rsnapshot", "diff", "alpha.0", "alpha.1"},
		{"veeamconfig", "job", "start", "--name", "j"},
		{"veeamconfig", "session", "stop", "--id", "1"},
		{"veeamconfig", "session", "list", "--24"},
		{"veeamconfig", "backup", "delete", "--id", "1"},
		{"urbackupsrv", "remove-unknown"},
		// The repository views: no call that locks, writes or deletes, no repository in an argument.
		{"restic", "snapshots", "--json", "--latest", "1"},
		{"restic", "snapshots", "--json", "--latest", "1", "--no-lock"},
		{"restic", "-r", "/srv/restic", "snapshots", "--json", "--latest", "1", "--no-lock", "--no-cache"},
		{"restic", "forget", "--prune", "--keep-last", "1"},
		{"restic", "prune"},
		{"restic", "unlock", "--remove-all"},
		{"restic", "check"},
		{"restic", "backup", "/"},
		{"borg", "list", "--last", "1", "--json"},
		{"borg", "list", "--last", "1", "--json", "--bypass-lock", "/srv/borg"},
		{"borg", "info", "--json", "--bypass-lock"},
		{"borg", "compact"},
		{"borg", "break-lock"},
		{"borg", "delete", "--force"},
		{"borg", "prune", "--keep-last", "1"},
		{"kopia", "maintenance", "run", "--full"},
		{"kopia", "snapshot", "delete", "k1", "--delete"},
		{"kopia", "snapshot", "list", "--json", "-n", "1", "--all"},
		{"kopia", "repository", "disconnect"},
		{"duplicati-server-util", "pause"},
		{"duplicati-server-util", "run", "1"},
		{"duplicati-server-util", "change-password", "x"},
		{"systemctl", "show", "-p", "LoadState,Environment,EnvironmentFiles", "--", "a.service", "b.service"},
		{"systemctl", "show", "-p", "Environment", "--", "restic-backup.service"},
	} {
		if Allowed(call[0], call[1:]) {
			t.Errorf("allowed: %q", call)
		}
	}
}
