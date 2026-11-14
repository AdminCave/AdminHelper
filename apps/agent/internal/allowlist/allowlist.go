// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package allowlist

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strings"
	"time"

	"adminhelper-agent/internal/execx"
	"adminhelper-agent/internal/logging"
)

var logger = logging.For("allowlist")

// ErrNotAllowed is the error of a call Run or RunEnv refused: the command or its arguments are not on
// the list, so it never started.
var ErrNotAllowed = errors.New("not on the command allowlist")

// classes are the variable parts a call may carry, each a whole argument or a part of one (`<node>` in
// a pvesh path). None may begin with '-', so none can pass for an option; unitarg alone may, and only
// stands right after "--" or behind a literal option in the same argument.
var classes = map[string]string{
	// A Proxmox node name: a hostname label (the short name collectProxmox cuts from the hostname).
	"node": `[A-Za-z0-9][A-Za-z0-9-]*`,
	// A Proxmox storage ID (pve-storage: a letter, then letters, digits, '-', '_', '.').
	"storage": `[A-Za-z][A-Za-z0-9._-]*`,
	// The UPID of a vzdump task as PVE writes it (pve-common PVE/UPID.pm encode: node, pid, pstart up to
	// nine digits, start time in upper-case hex, type, the VMID or nothing, the user): no other task
	// type, no '/' (it stands in a path) and no whitespace.
	"upid": `UPID:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?:[0-9A-F]{8}:[0-9A-F]{8,9}:[0-9A-F]{8}:vzdump:[0-9]*:[\x21-\x2E\x30-\x39\x3B-\x7E]+:`,
	// A device path from smartctl --scan, below /dev; no segment begins with '.', so no "..".
	"device": `/dev(/[A-Za-z0-9_,-][A-Za-z0-9_.,-]*)+`,
	// A smartctl device type from the scan (sat, nvme, megaraid,N, sat,12 …).
	"devtype": `[a-z0-9][a-z0-9_,+]*`,
	// A systemd unit name (systemd.unit(5): letters, digits, ":-_.\", '@' for instances).
	"unit": `[A-Za-z0-9:_.@\\][A-Za-z0-9:_.@\\-]*`,
	// A unit after "--" or inside an option: a unit name, or a root unit (-.slice, -.mount: systemd
	// escapes the path "/" to "-"), whose leading '-' cannot be read as an option there.
	"unitarg": `-\.[a-z]+|[A-Za-z0-9:_.@\\][A-Za-z0-9:_.@\\-]*`,
	// A container ID as docker ps prints it: 12 hex digits, 64 untruncated.
	"container": `[0-9a-f]{12,64}`,
	// A container name or ID as the probe's container target takes it (containerPattern).
	"containername": `[A-Za-z0-9][A-Za-z0-9_.-]*`,
	// A Windows service name, the class collectWatchedServices lets through (reWinServiceName).
	"winservice": `[A-Za-z0-9._$][A-Za-z0-9._$-]*`,
	// An absolute directory, meant for the agent's state directory (config.MonitorDir) but not bound to
	// it; no segment begins with '.', so no "..".
	"statedir": `(?:/[A-Za-z0-9_,-][A-Za-z0-9_.,-]*)+`,
	// A journal priority, 0 emerg … 7 debug.
	"priority": `[0-7]`,
	// A whole number of seconds.
	"seconds": `[0-9]+`,
	// A journal cursor as journalctl --show-cursor prints it (sd_journal_get_cursor(3): s=…;i=…;b=…;
	// m=…;t=…;x=…, hex values).
	"cursor": `[a-z0-9=;]+`,
	// A journal match on who logged an entry, as the log sensor takes it (logMatchPattern).
	"journalmatch": `(?:SYSLOG_IDENTIFIER|_COMM|CONTAINER_NAME)=[A-Za-z0-9._@/:+-]+`,
	// A package name as discovery asks for it (packagePattern).
	"package": `[a-z0-9][a-z0-9+._-]*`,
	// An rc.d script name as `service <name>` takes it (monitor's reRCScriptName): no '/', not "." or
	// "..", no leading '-'.
	"rcscript": `[A-Za-z0-9_][A-Za-z0-9._-]*`,
	// A FreeBSD base system name pkg audit checks (freebsdPkgName): FreeBSD- or FreeBSD-kernel- and a
	// release, "15.1" or with its patch level "15.1_2".
	"basepkg": `FreeBSD-(?:kernel-)?[0-9]+\.[0-9]+(?:_[0-9]+)?`,
	// A fail2ban jail as `fail2ban-client status` lists it (a section name of jail.conf).
	"jail": `[A-Za-z0-9_][A-Za-z0-9_.-]*`,
	// A UPS name as `upsc -l` lists it (probe's upsNamePattern): no '@' or ':', so a call with it names
	// no other host or port.
	"upsname": `[A-Za-z0-9_][A-Za-z0-9._-]*`,
	// The user of a unit pm2-<user> (probe's pm2Unit, useradd's NAME_REGEX), any but root: r, ro and
	// roo, a name on from root, or one that leaves root earlier.
	"pmuser": `root[a-z0-9_-]+|r(?:o(?:o[a-su-z0-9_-]|[a-np-z0-9_-])|[a-np-z0-9_-])[a-z0-9_-]*|r|ro|roo|[a-qs-z_][a-z0-9_-]*`,
}

// Classes returns a copy of the argument classes by name, each an unanchored pattern.
func Classes() map[string]string {
	return maps.Clone(classes)
}

// The journalctl calls of the log sensor: its fixed head, then a unit or none, a cursor or the
// interval, a match or none.
var (
	journalHead  = []string{"--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor", "--priority=<priority>"}
	journalCalls = journalVariants()
)

func journalVariants() [][]string {
	var calls [][]string
	for _, unit := range [][]string{nil, {"--unit=<unitarg>"}} {
		for _, from := range []string{"--after-cursor=<cursor>", "--since=-<seconds>s"} {
			for _, match := range [][]string{nil, {"--", "<journalmatch>"}} {
				call := append(append(append(append([]string{}, journalHead...), unit...), from), match...)
				calls = append(calls, call)
			}
		}
	}
	return calls
}

// The journalctl call of the system state after an OOM kill (monitor, oomProcesses): the kernel
// messages of this boot, err and above, of the last seconds. Its own entry, apart from the log
// sensor's calls: --dmesg and the priority are fixed.
var oomJournalCall = []string{"--no-pager", "--quiet", "--dmesg", "--output=cat", "--priority=3", "--since=-<seconds>s"}

// The sql sensor's MariaDB calls, by the client mariadb or, before 10.4.6, mysql. Each query is the
// sensor's own (mariadbQueries), under a statement timeout; probe's tests run every one through here.
var mariadbCalls = func() [][]string {
	var calls [][]string
	for _, query := range []string{
		"SELECT 1 AS ok",
		"SELECT VARIABLE_VALUE AS connections, @@GLOBAL.max_connections AS max_connections " +
			"FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'THREADS_CONNECTED'",
		"SHOW ALL SLAVES STATUS",
		"SELECT COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH), 0) AS size_bytes FROM information_schema.TABLES",
		"SELECT (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'ABORTED_CONNECTS') " +
			"AS aborted_connects, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS " +
			"WHERE VARIABLE_NAME = 'CONNECTION_ERRORS_MAX_CONNECTIONS') AS connection_errors_max_connections",
		"SELECT (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_VARIABLES WHERE VARIABLE_NAME = 'WSREP_ON') " +
			"AS wsrep_on, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_CLUSTER_STATUS') " +
			"AS cluster_status, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_READY') " +
			"AS ready, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_CLUSTER_SIZE') " +
			"AS cluster_size",
	} {
		calls = append(calls, []string{"--host=localhost", "--protocol=socket", "--batch", "--column-names",
			"--connect-timeout=5", "--execute=SET STATEMENT max_statement_time=5 FOR " + query})
	}
	return calls
}()

// The sql sensor's PostgreSQL calls: psql as the user postgres, with the sensor's own queries
// (postgresQueries).
var postgresCalls = func() [][]string {
	var calls [][]string
	for _, query := range []string{
		"SELECT 1",
		"SELECT count(*) FILTER (WHERE backend_type = 'client backend'), " +
			"current_setting('max_connections')::int FROM pg_stat_activity",
		"SELECT pg_is_in_recovery(), " +
			"EXISTS (SELECT 1 FROM pg_stat_wal_receiver WHERE status = 'streaming'), " +
			"CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0 " +
			"ELSE GREATEST(0, floor(extract(epoch FROM now() - pg_last_xact_replay_timestamp())))::bigint END",
		"SELECT sum(pg_database_size(oid))::bigint FROM pg_database",
		"SELECT max(age(datfrozenxid))::bigint FROM pg_database",
		"SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' " +
			"AND xact_start < now() - interval '1 hour'",
	} {
		calls = append(calls, []string{"-u", "postgres", "--", "psql", "--no-psqlrc", "--no-align",
			"--tuples-only", "--quiet", "--field-separator=\t", "--set=ON_ERROR_STOP=1",
			"--dbname=dbname=postgres connect_timeout=5 application_name=adminhelper-agent " +
				"options='-c statement_timeout=5s'",
			"--command=" + query})
	}
	return calls
}()

// commands is every call the agent's collectors (monitor), sensors (probe) and discovery may start:
// per command its argument lists, a literal argument as written, `<class>` for a variable part from
// classes, and `<class>...` as the last argument for one or more of them. They only read; a new call
// needs its entry here, and the tests of each package check its calls against it. Kept out on purpose
// (Konzept §3.6): calls that write, repair or touch the network, such as `apt-get check`, `zpool
// scrub`, `postfix check`, `docker exec` and the storage list `pvesh get /nodes/<n>/storage`, which
// activates every storage.
var commands = map[string][][]string{
	"docker": {
		{"info"},
		{"ps", "-a", "--format", "{{json .}}"},
		{"ps", "--all", "--quiet", "--no-trunc"},
		{"inspect", "--type", "container", "<container>..."},
		{"inspect", "--type", "container", "--", "<containername>"},
	},
	"pvesh": {
		{"get", "/nodes/<node>/status", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "vm", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "storage", "--output-format", "json"},
		{"get", "/nodes/<node>/storage/<storage>/content", "--content", "backup", "--output-format", "json"},
		// The backup details (buildBackupIndex): the vzdump jobs, the last failed vzdump task of the
		// node, and its log.
		{"get", "/cluster/backup", "--output-format", "json"},
		{"get", "/nodes/<node>/tasks", "--typefilter", "vzdump", "--statusfilter", "error", "--limit", "1", "--output-format", "json"},
		{"get", "/nodes/<node>/tasks/<upid>/log", "--limit", "10000", "--output-format", "json"},
		// The views pve_cluster, pve_jobs and pve_updates of the app sensor (probe/app_pve.go). Only
		// GET: apt/update lists the local cache and never refreshes it (that is POST, as are pvesh create,
		// set and delete, which stay off); /nodes/<node>/storage stays off, as listing it activates each
		// storage.
		{"get", "/cluster/status", "--output-format", "json"},
		{"get", "/cluster/ha/status/current", "--output-format", "json"},
		{"get", "/nodes/<node>/replication", "--output-format", "json"},
		{"get", "/nodes/<node>/tasks", "--typefilter", "vzdump", "--limit", "50", "--output-format", "json"},
		{"get", "/nodes/<node>/apt/update", "--output-format", "json"},
		{"get", "/nodes/<node>/subscription", "--output-format", "json"},
	},
	"zpool": {
		{"list", "-H", "-o", "name,size,alloc,free,cap,health,frag"},
		{"status", "-x"},
		// The pool details (zpoolDetails): scrub and vdev error counters as numbers, every vdev in one
		// map; OpenZFS 2.3 and newer (zpool-status(8)). Without -v: no names of damaged files.
		{"status", "-j", "--json-int", "--json-flat-vdevs"},
	},
	"smartctl": {
		{"--scan", "--json=c"},
		{"--all", "--json=c", "<device>"},
		{"--all", "--json=c", "-d", "<devtype>", "<device>"},
	},
	"systemctl": {
		{"list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"},
		{"list-units", "--type=service", "--all", "--full", "--no-legend", "--plain", "--no-pager"},
		{"list-unit-files", "--type=service", "--no-legend", "--no-pager"},
		{"list-units", "--state=failed", "--no-legend", "--plain"},
		{"show", "-p", "Id,Names", "--", "<unit>..."},
		{"show", "-p", "Id,Names,ActiveState,MainPID", "--", "<unit>..."},
		{"show", "-p", "Id,Names,Type,Result,ConditionResult,TriggeredBy,ConditionTimestampMonotonic", "--", "<unit>..."},
		{"show", "-p", "Id,Names,SubState,Result,ExecMainCode,ExecMainStatus,NRestarts,StateChangeTimestampMonotonic,MemoryCurrent", "--", "<unit>..."},
		{"show", "-p", "LoadState,ActiveState,SubState,NRestarts,ActiveEnterTimestampMonotonic,Result,ExecMainCode,ExecMainStatus,ExecMainExitTimestampMonotonic", "--", "<unitarg>"},
		{"show", "-p", "LoadState,ControlGroup", "--", "<unitarg>"},
		// Where a backup unit keeps its repository (probe, app_repo.go): its environment, read in the agent.
		{"show", "-p", "LoadState,Environment,EnvironmentFiles", "--", "<unitarg>"},
	},
	"journalctl": slices.Concat(journalCalls, [][]string{oomJournalCall}),
	"mariadb":    mariadbCalls,
	"mysql":      mariadbCalls,
	// psql as postgres; pm2 jlist as the user of a unit pm2-<user>, which only lists its apps;
	// BackupPC_serverMesg status hosts as backuppc (Debian's path and EPEL's), which reads the server's
	// status. Kept out: its other messages (backup, stop, server reload, log).
	"runuser": append(slices.Clone(postgresCalls),
		[]string{"-u", "<pmuser>", "--", "pm2", "jlist"},
		[]string{"-u", "backuppc", "--", "/usr/share/backuppc/bin/BackupPC_serverMesg", "status", "hosts"},
		[]string{"-u", "backuppc", "--", "/usr/share/BackupPC/bin/BackupPC_serverMesg", "status", "hosts"},
	),
	"dpkg-query": {{"--show", `--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "<package>..."}},
	"rpm":        {{"--query", `--queryformat=%{NAME}\n`, "<package>..."}},
	"sc": {
		{"query", "state=", "all"},
		{"query", "<winservice>"},
		{"queryex", "<winservice>"},
	},
	// Windows: the Service Control Manager's crash events 7031/7034 of the last 24 hours
	// (monitor.scmCrashArgs).
	"wevtutil": {{"qe", "System",
		"/q:*[System[Provider[@Name='Service Control Manager'] and (EventID=7031 or EventID=7034) and TimeCreated[timediff(@SystemTime) <= 86400000]]]",
		"/c:50", "/rd:true", "/f:xml"}},
	"needs-restarting": {{"-r"}},
	"timedatectl":      {{"show"}},
	"apt-get":          {{"-s", "dist-upgrade"}},
	"dnf":              {{"-C", "-q", "updateinfo", "list", "--security"}},
	// FreeBSD: the rc.d services, the versions of kernel and userland, and pkg audit against the local
	// vuln.xml only (never -F, which fetches it). onestatus is the probe's unit sensor: it answers
	// whether or not rc.conf enables the service.
	"service":         {{"-e"}, {"<rcscript>", "status"}, {"<rcscript>", "onestatus"}},
	"freebsd-version": {{"-kru"}, {"-u"}},
	"pkg":             {{"audit", "-q"}, {"audit", "-q", "<basepkg>..."}},
	// FreeBSD: the listening TCP sockets for the sensors' guard and discovery (probe, sockstatArgs).
	"sockstat": {{"-46", "-l", "-n", "-q", "-w", "-P", "tcp"}},
	// OPNsense: the configd read actions of the opnsense sensor, one per call of its views
	// (internal/opnsense, views).
	"configctl": {
		{"service", "list"},
		{"interface", "gateways", "status"},
		{"firmware", "product"},
		{"filter", "diag", "state_size"},
		{"interface", "show", "carp"},
		{"interface", "list", "ifconfig"},
	},
	// The read commands of the app sensor's views (probe, app_net.go). Kept out: `wg show … dump` and
	// `wg showconf` (they print the private key), fail2ban-client unban|reload|set, cscli decisions
	// add, tailscale netcheck.
	"wg":              {{"show", "all", "latest-handshakes"}, {"show", "all", "persistent-keepalive"}},
	"fail2ban-client": {{"ping"}, {"status"}, {"status", "<jail>"}},
	"cscli":           {{"bouncers", "list", "-o", "json"}},
	"tailscale":       {{"status", "--json", "--peers=false"}},
	// The read commands of the DNS and time views (probe, app_dns.go). Kept out: `rndc stats` (writes
	// the statistics file), `unbound-control stats` (resets the counters), chronyc makestep|burst.
	"rndc":            {{"status"}},
	"unbound-control": {{"stats_noreset"}},
	"chronyc":         {{"-c", "tracking"}},
	"ntpq":            {{"-c", "rv 0 leap,stratum,offset"}},
	// The UPS views (probe, app_ups.go): the UPS list and the variables of one UPS from the upsd on
	// localhost, the status report of the apcupsd on localhost. Kept out: upscmd and upsrw (commands
	// and settings to the UPS), upsmon -c (fsd shuts every client down), upsc against another host,
	// apcaccess -h/-f.
	"upsc":      {{"-l", "localhost"}, {"<upsname>@localhost"}},
	"apcaccess": {{"-u", "status"}},
	// The views pbs_status, ceph_health and zfs_snapshots (probe, app_pbs.go). proxmox-backup-debug
	// only with api get (api set, create and delete write through the API); proxmox-backup-manager stays
	// off. ceph only health and df as JSON (ceph … set, osd out and the like change the cluster);
	// sanoid only --monitor-snapshots (--cron, --take-snapshots and --prune-snapshots change snapshots).
	"proxmox-backup-debug": {
		{"api", "get", "/config/datastore", "--output-format", "json"},
		{"api", "get", "/status/datastore-usage", "--output-format", "json"},
		{"api", "get", "/nodes/localhost/tasks", "--typefilter", "garbage_collection", "--limit", "50", "--output-format", "json"},
		{"api", "get", "/nodes/localhost/tasks", "--typefilter", "verif", "--limit", "50", "--output-format", "json"},
		{"api", "get", "/nodes/localhost/tasks", "--typefilter", "sync", "--limit", "50", "--output-format", "json"},
		{"api", "get", "/nodes/localhost/tasks", "--typefilter", "prune", "--limit", "50", "--output-format", "json"},
	},
	// The web server views (probe, app_web.go): the configuration tests, which read the configuration and
	// start nothing, the dump of nginx's configuration and Apache's list of its files. Kept out: nginx
	// -s (signals the master: stop, reload, reopen), nginx -c/-g, apachectl start|stop|restart|graceful
	// and -k, haproxy without -c (starts a proxy) and with -sf/-st (stops the running one).
	"nginx":      {{"-t"}, {"-T"}},
	"apache2ctl": {{"-t"}, {"-t", "-D", "DUMP_INCLUDES"}},
	"apachectl":  {{"-t"}, {"-t", "-D", "DUMP_INCLUDES"}},
	"haproxy":    {{"-c", "-q", "-f", "/etc/haproxy/haproxy.cfg"}},
	"ceph":       {{"health", "-f", "json"}, {"df", "-f", "json"}},
	"sanoid":     {{"--monitor-snapshots"}},
	// Veeam Agent for Linux (probe, app_backup.go): the list of sessions. Kept out: job start, session
	// stop, backup delete and every other veeamconfig command.
	"veeamconfig": {{"session", "list"}},
	// The repository views (probe, app_repo.go): the newest snapshot, without a lock and without writing
	// restic's cache; the repository and its password come in the environment. Kept out: restic
	// backup|forget|prune|unlock|check and any call that locks, borg create|prune|compact|delete|
	// break-lock and any list without --bypass-lock, kopia snapshot create|delete and maintenance, and
	// duplicati-server-util's other commands (pause, run, logout, change-password).
	"restic":                {{"snapshots", "--json", "--latest", "1", "--no-lock", "--no-cache"}},
	"borg":                  {{"list", "--last", "1", "--json", "--bypass-lock"}},
	"kopia":                 {{"snapshot", "list", "--json", "-n", "1"}},
	"duplicati-server-util": {{"health"}},
	// The host sensor's thin pool view (probe, host_storage.go): attributes and fill levels only. The md
	// view reads sysfs, so mdadm stays off the list (its --action, --fail and --remove write). Kept out:
	// lvchange, lvextend, dmsetup and any other lvs argument list.
	"lvs": {{"--reportformat", "json", "-o", "lv_attr,data_percent,metadata_percent"}},
	// The host sensor's hardware views (probe, host_hw.go): every controller's state as JSON without
	// storcli's log file, the HPE status and configuration, the sensor list from the SDR cache and the
	// dump that writes the cache, by a fixed file name into an absolute directory without ".." (the agent
	// passes its state directory). Kept out: storcli start|stop|set|
	// delete|… (start learn starts a battery learn cycle, delete events clears the event log), any call
	// without nolog, ipmitool sel (sel elist loads the BMC, sel clear deletes the log), chassis, raw,
	// mc, user, lan and any sdr call without the cache.
	"storcli64": {{"/call", "show", "all", "J", "nolog"}},
	"perccli64": {{"/call", "show", "all", "J", "nolog"}},
	"ssacli":    {{"ctrl", "all", "show", "status"}, {"ctrl", "all", "show", "config"}},
	"ipmitool": {
		{"-S", "<statedir>/.ipmi-sdr.cache", "sdr", "elist"},
		{"sdr", "dump", "<statedir>/.ipmi-sdr.cache.new"},
	},
}

// call is one argument list of commands, compiled: one pattern per argument, the last one repeated
// when variadic.
type call struct {
	args     []*regexp.Regexp
	variadic bool
}

var (
	reClass  = regexp.MustCompile(`<([a-z]+)>`)
	compiled = compile(commands)
)

// compile turns the table into anchored patterns; an unknown class is a programming error.
func compile(list map[string][][]string) map[string][]call {
	out := make(map[string][]call, len(list))
	for name, calls := range list {
		for _, args := range calls {
			var c call
			for i, arg := range args {
				if i == len(args)-1 && strings.HasSuffix(arg, "...") {
					arg, c.variadic = strings.TrimSuffix(arg, "..."), true
				}
				c.args = append(c.args, regexp.MustCompile("^"+argPattern(arg)+"$"))
			}
			out[name] = append(out[name], c)
		}
	}
	return out
}

// argPattern quotes the literal parts of one argument and replaces each `<class>` by its pattern.
func argPattern(arg string) string {
	var b strings.Builder
	last := 0
	for _, m := range reClass.FindAllStringSubmatchIndex(arg, -1) {
		class, ok := classes[arg[m[2]:m[3]]]
		if !ok {
			panic("allowlist: unknown argument class: " + arg)
		}
		b.WriteString(regexp.QuoteMeta(arg[last:m[0]]) + "(?:" + class + ")")
		last = m[1]
	}
	b.WriteString(regexp.QuoteMeta(arg[last:]))
	return b.String()
}

// Allowed reports whether name with args is on the list, by Key(name).
func Allowed(name string, args []string) bool {
	for _, c := range compiled[Key(name, runtime.GOOS == "windows")] {
		if c.matches(args) {
			return true
		}
	}
	return false
}

// Key is the list key of name. An absolute name counts by its base name: smartctl runs by the path
// exec.LookPath found, which on Windows ends in ".exe" (PATHEXT), so there the extension goes too, in
// any case. A name that starts with "/" is absolute on every host: the FreeBSD calls name
// /usr/sbin/service and the like, the tests without a build tag check them on Windows as well, and
// there filepath.IsAbs wants a volume.
func Key(name string, windows bool) string {
	if filepath.IsAbs(name) || strings.HasPrefix(name, "/") {
		name = filepath.Base(name)
	}
	if windows && strings.EqualFold(filepath.Ext(name), ".exe") {
		name = name[:len(name)-len(".exe")]
	}
	return name
}

func (c call) matches(args []string) bool {
	if len(args) < len(c.args) || (!c.variadic && len(args) != len(c.args)) {
		return false
	}
	for i, arg := range args {
		if !c.args[min(i, len(c.args)-1)].MatchString(arg) {
			return false
		}
	}
	return true
}

// Run runs a command under timeout and ctx, whichever ends first; see RunEnv.
func Run(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
	return RunEnv(ctx, timeout, nil, name, args...)
}

// RunEnv is the one place the agent's collectors, sensors and discovery start a command (execx.RunEnv,
// its errors there). A call off the list does not start and returns ErrNotAllowed. env is added to the
// agent's environment; a later entry of the same key wins (os/exec).
func RunEnv(ctx context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
	if !Allowed(name, args) {
		logger.Warnf("%s call refused, %s", filepath.Base(name), ErrNotAllowed)
		return nil, fmt.Errorf("%s: %w", filepath.Base(name), ErrNotAllowed)
	}
	return execx.RunEnv(ctx, timeout, env, name, args...)
}
