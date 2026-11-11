// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package main

import (
	"encoding/json"
	"io/fs"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"
)

// pkg runs a package's scripts as `/bin/sh -c "set -- <name>-<version>\n<script>"` and tells them
// about the install through the environment: PKG_UPGRADE on an upgrade, PKG_ROOTDIR ("/" unless
// pkg -r), PKG_CHROOTED under pkg -c (pkg-script(5), libpkg/scripts.c). On an upgrade it runs the
// old package's pre-deinstall, replaces the files, then runs the new package's post-install. These
// tests run the FreeBSD scripts that way with Linux's /bin/sh against a service(8) stub, and
// build-pkg.sh against a pkg stub; the real pkg create, repo and install run on the FreeBSD box.

const (
	servicePath  = "/usr/sbin/service"
	pkgEtc       = "/usr/local/etc/"
	pkgCronEntry = "/usr/local/etc/cron.d/adminhelper"
	pkgFrpcTOML  = "/usr/local/etc/adminhelper/frp/frpc.toml"
)

// absPath finds an absolute path in a line of shell code: a '/' and a letter after anything that
// cannot end a name, also after "${PKG_ROOTDIR}".
var absPath = regexp.MustCompile(`(^|[^A-Za-z0-9_.])/[A-Za-z]`)

// serviceStub keeps adminhelper_frpc's state as files in $AH_SERVICE_STATE: rcvar for an
// adminhelper_frpc_enable in rc.conf, enabled for one set to YES, running for a running frpc. It
// logs every call to calls and every start to starts and answers as rc.subr does: enabled by its
// exit status, restart only an enabled one, delete fails without an rcvar.
const serviceStub = `#!/bin/sh
s=$AH_SERVICE_STATE
echo "$*" >> "$s/calls"
[ "$1" = adminhelper_frpc ] || exit 1
case "$2" in
    enabled) [ -f "$s/enabled" ] ;;
    faststop) rm -f "$s/running" ;;
    delete) [ -f "$s/rcvar" ] || exit 1; rm -f "$s/rcvar" "$s/enabled" ;;
    restart)
        if [ -f "$s/enabled" ]; then echo adminhelper_frpc >> "$s/starts"; : > "$s/running"
        else echo "Cannot 'restart' adminhelper_frpc."; fi ;;
    *) exit 1 ;;
esac
`

type pkgHost struct {
	root, state, path string
}

// newPkgHost is a FreeBSD host faked under a temporary root, with the cron entry and frpc.toml in
// place and adminhelper_frpc in the given state: "" never enabled, "NO", "YES" or "running".
func newPkgHost(t *testing.T, frpc string) *pkgHost {
	t.Helper()
	h := &pkgHost{root: t.TempDir(), state: t.TempDir()}
	bin := t.TempDir()
	writeFile(t, filepath.Join(bin, "service"), serviceStub, 0o755)
	h.path = bin + string(os.PathListSeparator) + os.Getenv("PATH")
	writeFile(t, filepath.Join(h.root, pkgCronEntry), "cron\n", 0o644)
	writeFile(t, filepath.Join(h.root, pkgFrpcTOML), "toml\n", 0o600)
	state := map[string][]string{"NO": {"rcvar"}, "YES": {"rcvar", "enabled"}, "running": {"rcvar", "enabled", "running"}}
	for _, f := range state[frpc] {
		writeFile(t, filepath.Join(h.state, f), "", 0o600)
	}
	return h
}

func writeFile(t *testing.T, path, data string, mode os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), mode); err != nil {
		t.Fatal(err)
	}
}

// cleanEnv is the test's environment without the variables pkg or build-pkg.sh read, so neither the
// caller's shell nor CI decides a case.
func cleanEnv() []string {
	return slices.DeleteFunc(os.Environ(), func(kv string) bool {
		name, _, _ := strings.Cut(kv, "=")
		return strings.HasPrefix(name, "PKG_") || slices.Contains([]string{"VERSION", "AGENT_BINARY",
			"FRPC_BINARY", "OUT_DIR", "TMPDIR", "AH_SERVICE_STATE", "AH_PKG_LOG"}, name)
	})
}

// run runs one script of apps/agent/freebsd as pkg does, with /usr/local/etc pointing into the
// host's root and service(8) at the stub, and returns the service calls it made. env adds to what pkg always
// sets; a PKG_ROOTDIR in env replaces "/". Every script has to exit 0: pkg in developer mode fails
// on any other status.
func (h *pkgHost) run(t *testing.T, script string, env ...string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("../../freebsd", script))
	if err != nil {
		t.Fatal(err)
	}
	body := string(data)
	// A path the test does not redirect would reach the real host.
	redirected := strings.NewReplacer(servicePath, "", pkgEtc, "", "/dev/null", "")
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		if absPath.MatchString(redirected.Replace(line)) {
			t.Fatalf("%s: %q names a path the test does not redirect", script, line)
		}
	}
	body = strings.ReplaceAll(body, servicePath, filepath.Join(filepath.SplitList(h.path)[0], "service"))
	body = strings.ReplaceAll(body, pkgEtc, h.root+pkgEtc)
	if err := os.Remove(filepath.Join(h.state, "calls")); err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	cmd := exec.Command("/bin/sh", "-c", "set -- adminhelper-agent-0.47.0\n"+body)
	cmd.Env = append(cleanEnv(), "PATH="+h.path, "AH_SERVICE_STATE="+h.state, "PKG_NAME=adminhelper-agent",
		"PKG_PREFIX=/usr/local", "PKG_ROOTDIR=/")
	cmd.Env = append(cmd.Env, env...)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%s %v: %v\n%s", script, env, err, out)
	}
	return h.lines(t, "calls")
}

func (h *pkgHost) lines(t *testing.T, name string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(h.state, name))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func (h *pkgHost) has(name string) bool {
	_, err := os.Stat(filepath.Join(h.state, name))
	return err == nil
}

func exists(t *testing.T, path string) bool {
	t.Helper()
	_, err := os.Stat(path)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return err == nil
}

func TestPkgUpgradeRestartsAnEnabledTunnel(t *testing.T) {
	h := newPkgHost(t, "running")
	if calls := h.run(t, "pre-deinstall", "PKG_UPGRADE=true"); calls != nil {
		t.Errorf("old pre-deinstall on an upgrade calls %q, want nothing", calls)
	}
	calls := h.run(t, "post-install", "PKG_UPGRADE=true")
	if want := []string{"adminhelper_frpc enabled", "adminhelper_frpc restart"}; !slices.Equal(calls, want) {
		t.Errorf("new post-install calls %q, want %q", calls, want)
	}
	// Only a start after the files were replaced runs the new frpc.
	if starts := h.lines(t, "starts"); !slices.Equal(starts, []string{"adminhelper_frpc"}) {
		t.Errorf("starts = %q, want one by the new post-install", starts)
	}
	if !h.has("enabled") || !h.has("running") {
		t.Error("tunnel after the upgrade is not enabled and running")
	}
	if !exists(t, filepath.Join(h.root, pkgCronEntry)) {
		t.Error("upgrade deleted the cron entry")
	}
}

func TestPkgUpgradeLeavesADisabledTunnelStopped(t *testing.T) {
	for _, state := range []string{"", "NO"} {
		h := newPkgHost(t, state)
		h.run(t, "pre-deinstall", "PKG_UPGRADE=true")
		calls := h.run(t, "post-install", "PKG_UPGRADE=true")
		if want := []string{"adminhelper_frpc enabled"}; !slices.Equal(calls, want) {
			t.Errorf("rcvar %q: post-install calls %q, want %q", state, calls, want)
		}
		if h.has("running") || h.has("starts") {
			t.Errorf("rcvar %q: upgrade started the tunnel", state)
		}
	}
}

func TestPkgInstallStartsNothing(t *testing.T) {
	h := newPkgHost(t, "")
	if calls := h.run(t, "post-install"); calls != nil {
		t.Errorf("post-install of a fresh install calls %q, want nothing", calls)
	}
}

func TestPkgRemovalStopsTheTunnelAndDeletesTheCronEntry(t *testing.T) {
	for _, state := range []string{"running", "NO", ""} {
		h := newPkgHost(t, state)
		calls := h.run(t, "pre-deinstall")
		if want := []string{"adminhelper_frpc faststop", "adminhelper_frpc delete"}; !slices.Equal(calls, want) {
			t.Errorf("rcvar %q: pre-deinstall calls %q, want %q", state, calls, want)
		}
		if h.has("running") || h.has("rcvar") {
			t.Errorf("rcvar %q: tunnel still running or its rcvar still set", state)
		}
		if exists(t, filepath.Join(h.root, pkgCronEntry)) {
			t.Errorf("rcvar %q: cron entry left behind", state)
		}
		if !exists(t, filepath.Join(h.root, pkgFrpcTOML)) {
			t.Errorf("rcvar %q: removal deleted the configuration", state)
		}
	}
}

// Under pkg -r the scripts run on the host for a package in another root, under pkg -c inside a
// chroot that shares the host's processes; neither may touch the host's tunnel.
func TestPkgScriptsLeaveTheServiceAloneInAnotherRoot(t *testing.T) {
	other := t.TempDir()
	for _, tc := range []struct {
		name string
		env  []string
		root string // the root the package is in, from the host's view
	}{
		{"pkg -r", []string{"PKG_ROOTDIR=" + other}, other},
		{"pkg -r with a final slash", []string{"PKG_ROOTDIR=" + other + "/"}, other},
		{"pkg -c", []string{"PKG_CHROOTED=true"}, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newPkgHost(t, "running")
			// run points the scripts' paths into h.root; the package's root lies before that.
			pkgCron := filepath.Join(tc.root, h.root, pkgCronEntry)
			writeFile(t, pkgCron, "cron\n", 0o644)
			if calls := h.run(t, "post-install", append(tc.env, "PKG_UPGRADE=true")...); calls != nil {
				t.Errorf("post-install on an upgrade calls %q, want nothing", calls)
			}
			if calls := h.run(t, "pre-deinstall", tc.env...); calls != nil {
				t.Errorf("pre-deinstall calls %q, want nothing", calls)
			}
			if !h.has("enabled") || !h.has("running") {
				t.Error("host's tunnel is no longer enabled and running")
			}
			if exists(t, pkgCron) {
				t.Errorf("cron entry of the package's root %s left behind", pkgCron)
			}
			if tc.root != "" && !exists(t, filepath.Join(h.root, pkgCronEntry)) {
				t.Error("removal from another root deleted the host's cron entry")
			}
		})
	}
}

// pkgStub logs every call to $AH_PKG_LOG/calls. For create it keeps what pkg would pack in
// $AH_PKG_LOG/create-<call>: the metadata directory, the plist and the stage tree, as the build
// deletes them; and it leaves an empty package in the output directory.
const pkgStub = `#!/bin/sh
log=$AH_PKG_LOG
echo "$*" >> "$log/calls"
[ "$1" = create ] || exit 0
d="$log/create-$(($(wc -l < "$log/calls")))"
shift
while [ $# -gt 0 ]; do
    case "$1" in
        -m) m=$2 ;;
        -r) r=$2 ;;
        -p) p=$2 ;;
        -o) o=$2 ;;
        *) echo "pkg stub: unexpected argument $1" >&2; exit 2 ;;
    esac
    shift 2
done
mkdir -p "$d" "$o"
cp -Rp "$m" "$d/meta"
cp "$p" "$d/plist"
cp -Rp "$r" "$d/stage"
: > "$o/adminhelper-agent-stub.pkg"
`

type pkgBuild struct {
	dir, out, log, tmp string
	env                []string
}

// newPkgBuild prepares a run of build-pkg.sh with stub binaries, a stub pkg and a stale package of
// an earlier build in the output directory.
func newPkgBuild(t *testing.T) *pkgBuild {
	t.Helper()
	b := &pkgBuild{dir: t.TempDir()}
	b.out, b.log, b.tmp = filepath.Join(b.dir, "out"), filepath.Join(b.dir, "log"), filepath.Join(b.dir, "tmp")
	bin := filepath.Join(b.dir, "bin")
	writeFile(t, filepath.Join(bin, "pkg"), pkgStub, 0o755)
	writeFile(t, filepath.Join(b.dir, "agent"), "agent binary\n", 0o600)
	writeFile(t, filepath.Join(b.dir, "frpc"), "frpc binary\n", 0o600)
	writeFile(t, filepath.Join(b.dir, "key.pem"), "key\n", 0o600)
	writeFile(t, filepath.Join(b.out, "freebsd/FreeBSD:14:amd64/All/stale.pkg"), "", 0o644)
	for _, d := range []string{b.log, b.tmp} {
		if err := os.Mkdir(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	b.env = append(cleanEnv(), "PATH="+bin+string(os.PathListSeparator)+os.Getenv("PATH"), "AH_PKG_LOG="+b.log,
		"TMPDIR="+b.tmp, "AGENT_BINARY="+filepath.Join(b.dir, "agent"), "FRPC_BINARY="+filepath.Join(b.dir, "frpc"),
		"OUT_DIR="+b.out)
	return b
}

func (b *pkgBuild) run(env ...string) ([]byte, error) {
	cmd := exec.Command("bash", "../../build-pkg.sh")
	cmd.Env = append(slices.Clone(b.env), env...)
	return cmd.CombinedOutput()
}

func (b *pkgBuild) calls(t *testing.T) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(b.log, "calls"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

// tree maps each file below dir to its mode and content.
func tree(t *testing.T, dir string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, path)
		files[rel] = info.Mode().String() + " " + string(data)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}

func readRepoFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestBuildPkgPacksBothABIsAndSignsTheirRepos(t *testing.T) {
	abis := []string{"FreeBSD:14:amd64", "FreeBSD:15:amd64"}
	for _, signed := range []bool{true, false} {
		b := newPkgBuild(t)
		var env []string
		if signed {
			env = append(env, "PKG_REPO_KEY="+filepath.Join(b.dir, "key.pem"))
		}
		if out, err := b.run(append(env, "VERSION=0.47.0")...); err != nil {
			t.Fatalf("signed=%v: build-pkg.sh: %v\n%s", signed, err, out)
		}
		var want []string
		for _, abi := range abis {
			want = append(want, "create -o "+filepath.Join(b.out, "freebsd", abi, "All"))
			if signed {
				want = append(want, "repo "+filepath.Join(b.out, "freebsd", abi)+" rsa:"+filepath.Join(b.dir, "key.pem"))
			}
		}
		var got []string
		for _, c := range b.calls(t) {
			// The work directory of -m, -r and -p is a random one; its content is checked below.
			if f := strings.Fields(c); len(f) == 9 && f[0] == "create" && f[7] == "-o" {
				c = "create -o " + f[8]
			}
			got = append(got, c)
		}
		if !slices.Equal(got, want) {
			t.Fatalf("signed=%v: pkg calls\n%q\nwant\n%q", signed, got, want)
		}
		for i, abi := range abis {
			n := 1 + i
			if signed {
				n = 1 + 2*i
			}
			checkPkgCreate(t, filepath.Join(b.log, "create-"+string(rune('0'+n))), abi)
		}
		if exists(t, filepath.Join(b.out, "freebsd/FreeBSD:14:amd64/All/stale.pkg")) {
			t.Errorf("signed=%v: a package of an earlier build is still in the repository", signed)
		}
		if left, _ := os.ReadDir(b.tmp); len(left) > 0 {
			t.Errorf("signed=%v: work directory left behind: %v", signed, left)
		}
	}
}

// checkPkgCreate checks what one pkg create got: a manifest pkg accepts for abi, the scripts of
// apps/agent/freebsd, the plist and a stage tree with exactly its files.
func checkPkgCreate(t *testing.T, dir, abi string) {
	t.Helper()
	var manifest map[string]any
	if err := json.Unmarshal([]byte(readRepoFile(t, filepath.Join(dir, "meta/+MANIFEST"))), &manifest); err != nil {
		t.Fatalf("%s: +MANIFEST is no JSON: %v", abi, err)
	}
	for key, want := range map[string]string{"name": "adminhelper-agent", "version": "0.47.0", "abi": abi,
		"prefix": "/usr/local"} {
		if manifest[key] != want {
			t.Errorf("%s: manifest %s = %v, want %q", abi, key, manifest[key], want)
		}
	}
	// The fields without which pkg refuses a package (libpkg/pkg.c, pkg_is_valid).
	for _, key := range []string{"origin", "comment", "desc", "maintainer", "www"} {
		if s, _ := manifest[key].(string); s == "" {
			t.Errorf("%s: manifest lacks %s", abi, key)
		}
	}
	scripts := map[string]string{"+POST_INSTALL": "post-install", "+PRE_DEINSTALL": "pre-deinstall"}
	meta := tree(t, filepath.Join(dir, "meta"))
	if len(meta) != 1+len(scripts) {
		t.Errorf("%s: metadata directory holds %d files, want +MANIFEST and %d scripts", abi, len(meta), len(scripts))
	}
	for name, src := range scripts {
		if got := readRepoFile(t, filepath.Join(dir, "meta", name)); got != readRepoFile(t, filepath.Join("../../freebsd", src)) {
			t.Errorf("%s: %s is not freebsd/%s", abi, name, src)
		}
	}
	plist := "@owner root\n@group wheel\nbin/adminhelper-agent\nlibexec/adminhelper/frpc\netc/rc.d/adminhelper_frpc\n" +
		"etc/newsyslog.conf.d/adminhelper.conf\n"
	if got := readRepoFile(t, filepath.Join(dir, "plist")); got != plist {
		t.Errorf("%s: plist\n%s\nwant\n%s", abi, got, plist)
	}
	want := map[string]string{
		"usr/local/bin/adminhelper-agent":     "-rwxr-xr-x agent binary\n",
		"usr/local/libexec/adminhelper/frpc":  "-rwxr-xr-x frpc binary\n",
		"usr/local/etc/rc.d/adminhelper_frpc": "-rwxr-xr-x " + readRepoFile(t, "../../freebsd/adminhelper_frpc"),
		// /etc/newsyslog.conf reads /usr/local/etc/newsyslog.conf.d/[!.]*.conf.
		"usr/local/etc/newsyslog.conf.d/adminhelper.conf": "-rw-r--r-- " + readRepoFile(t, "../../freebsd/newsyslog.conf"),
	}
	if got := tree(t, filepath.Join(dir, "stage")); !maps.Equal(got, want) {
		t.Errorf("%s: stage tree\n%v\nwant\n%v", abi, slices.Sorted(maps.Keys(got)), slices.Sorted(maps.Keys(want)))
	}
}

// Each refusal comes before the build touches the output directory, so a failed build keeps the
// repository of the last one.
func TestBuildPkgRefusesBadInput(t *testing.T) {
	var cases [][]string
	for _, version := range []string{"v0.47.0", "0.47.0-beta.1", "0.47.0_1", "0.47,1", "0.47.0 ", "0.47.ä", ""} {
		// Under de_DE.UTF-8 bash's [A-Za-z] also matches letters like ä.
		cases = append(cases, []string{"VERSION=" + version, "LC_ALL=de_DE.UTF-8"})
	}
	for _, input := range []string{"PKG_REPO_KEY", "AGENT_BINARY", "FRPC_BINARY"} {
		cases = append(cases, []string{"VERSION=0.47.0", input + "=" + filepath.Join(t.TempDir(), "missing")})
	}
	for _, env := range cases {
		b := newPkgBuild(t)
		out, err := b.run(env...)
		if err == nil {
			t.Errorf("%q: build-pkg.sh succeeded\n%s", env, out)
		}
		if calls := b.calls(t); calls != nil {
			t.Errorf("%q: pkg called: %q", env, calls)
		}
		if !exists(t, filepath.Join(b.out, "freebsd/FreeBSD:14:amd64/All/stale.pkg")) {
			t.Errorf("%q: output directory changed before the check", env)
		}
	}
}
