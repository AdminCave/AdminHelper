// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"io/fs"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// pkg runs a package's scripts as `/bin/sh -c "set -- <name>-<version>\n<script>"` and tells them
// about the install through the environment: PKG_UPGRADE on an upgrade, PKG_ROOTDIR ("/" unless
// pkg -r), PKG_CHROOTED under pkg -c (pkg-script(5), libpkg/scripts.c). On an upgrade it runs the
// old package's pre-deinstall, replaces the files, then runs the new package's post-install. These
// tests run the FreeBSD scripts that way with Linux's /bin/sh against a service(8) stub, and
// build-pkg.sh against a pkg stub; the real pkg create, repo and install run on the FreeBSD box.
// The plugin's scripts are tested in apps/agent/opnsense.

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

// repoKey is the signing key of the builds, made once; openssl derives its public part.
var repoKey = sync.OnceValues(func() (*rsa.PrivateKey, error) { return rsa.GenerateKey(rand.Reader, 2048) })

// pemKey is key in the PKCS#8 PEM form openssl genrsa writes.
func pemKey(t *testing.T, key any) string {
	t.Helper()
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
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
	key, err := repoKey()
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(b.dir, "key.pem"), pemKey(t, key), 0o600)
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
			// The agent's package, then the plugin's; pkg repo takes both.
			create := "create -o " + filepath.Join(b.out, "freebsd", abi, "All")
			want = append(want, create, create)
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
			n := 1 + 2*i
			if signed {
				n = 1 + 3*i
			}
			agent := filepath.Join(b.log, "create-"+strconv.Itoa(n))
			checkPkgCreate(t, agent, abi)
			checkPluginCreate(t, filepath.Join(b.log, "create-"+strconv.Itoa(n+1)), agent, abi, signed)
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

// pluginSrc is the plugin's tree, which build-pkg.sh packs below /usr/local.
const pluginSrc = "../../opnsense/src"

// opnsenseSeries is the OPNsense series that runs on each ABI.
var opnsenseSeries = map[string]string{"FreeBSD:14:amd64": "26.1", "FreeBSD:15:amd64": "26.7"}

// checkPluginCreate checks what the pkg create of os-adminhelper got: a manifest that depends on
// the agent's package of agentDir, the version file of OPNsense's plugins.mk as file and as
// annotations, the scripts of apps/agent/opnsense, and a plist and stage tree with every file of
// the plugin's tree in its mode, and with a key the key's public part.
func checkPluginCreate(t *testing.T, dir, agentDir, abi string, signed bool) {
	t.Helper()
	version := map[string]string{
		"product_abi": opnsenseSeries[abi], "product_arch": "amd64", "product_conflicts": "",
		"product_email": "packages@admincave.com", "product_hash": "", "product_id": "os-adminhelper",
		"product_name": "adminhelper", "product_tier": "4", "product_version": "0.47.0",
		"product_website": "https://admincave.com",
	}
	var manifest, agent map[string]any
	for path, v := range map[string]*map[string]any{dir: &manifest, agentDir: &agent} {
		if err := json.Unmarshal([]byte(readRepoFile(t, filepath.Join(path, "meta/+MANIFEST"))), v); err != nil {
			t.Fatalf("%s: +MANIFEST is no JSON: %v", abi, err)
		}
	}
	for key, want := range map[string]string{"name": "os-adminhelper", "version": "0.47.0", "abi": abi,
		"prefix": "/usr/local", "origin": "opnsense/os-adminhelper"} {
		if manifest[key] != want {
			t.Errorf("%s: plugin manifest %s = %v, want %q", abi, key, manifest[key], want)
		}
	}
	for _, key := range []string{"comment", "desc", "maintainer", "www"} {
		if s, _ := manifest[key].(string); s == "" {
			t.Errorf("%s: plugin manifest lacks %s", abi, key)
		}
	}
	deps := map[string]any{agent["name"].(string): map[string]any{"origin": agent["origin"], "version": agent["version"]}}
	if got, _ := json.Marshal(manifest["deps"]); string(got) != mustJSON(t, deps) {
		t.Errorf("%s: plugin deps %s, want %s", abi, got, mustJSON(t, deps))
	}
	// OPNsense reads the tier of a remote plugin from the annotations (firmware/query.sh).
	if got, _ := json.Marshal(manifest["annotations"]); string(got) != mustJSON(t, version) {
		t.Errorf("%s: plugin annotations %s, want %s", abi, got, mustJSON(t, version))
	}

	scripts := map[string]string{"+POST_INSTALL": "post-install", "+POST_DEINSTALL": "post-deinstall"}
	if meta := tree(t, filepath.Join(dir, "meta")); len(meta) != 1+len(scripts) {
		t.Errorf("%s: plugin metadata holds %v, want +MANIFEST and %d scripts", abi, slices.Sorted(maps.Keys(meta)), len(scripts))
	}
	for name, src := range scripts {
		if got := readRepoFile(t, filepath.Join(dir, "meta", name)); got != readRepoFile(t, filepath.Join("../../opnsense", src)) {
			t.Errorf("%s: plugin %s is not opnsense/%s", abi, name, src)
		}
	}

	var files []string
	want := map[string]string{}
	err := filepath.WalkDir(pluginSrc, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(pluginSrc, path)
		mode := "-rw-r--r-- "
		if info.Mode()&0o100 != 0 {
			mode = "-rwxr-xr-x "
		}
		files = append(files, rel)
		want["usr/local/"+rel] = mode + readRepoFile(t, path)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	slices.Sort(files)
	files = append(files, "opnsense/version/adminhelper")
	stage := tree(t, filepath.Join(dir, "stage"))
	var file map[string]string
	if err := json.Unmarshal([]byte(strings.TrimPrefix(stage["usr/local/opnsense/version/adminhelper"], "-rw-r--r-- ")), &file); err != nil {
		t.Errorf("%s: version file %q: %v", abi, stage["usr/local/opnsense/version/adminhelper"], err)
	} else if !maps.Equal(file, version) {
		t.Errorf("%s: version file %v, want %v", abi, file, version)
	}
	want["usr/local/opnsense/version/adminhelper"] = stage["usr/local/opnsense/version/adminhelper"]
	if signed {
		const pub = "etc/pkg/keys/AdminHelper.pub"
		files = append(files, pub)
		checkPublicKey(t, abi, stage["usr/local/"+pub])
		want["usr/local/"+pub] = stage["usr/local/"+pub]
		// The repository script names that file to pkg.
		repo := stage["usr/local/opnsense/scripts/firmware/repos/AdminHelper.sh"]
		if !strings.Contains(repo, "\npubkey=/usr/local/"+pub+"\n") {
			t.Errorf("%s: the repository script does not name /usr/local/%s", abi, pub)
		}
	}
	plist := "@owner root\n@group wheel\n" + strings.Join(files, "\n") + "\n"
	if got := readRepoFile(t, filepath.Join(dir, "plist")); got != plist {
		t.Errorf("%s: plugin plist\n%s\nwant\n%s", abi, got, plist)
	}
	if !maps.Equal(stage, want) {
		t.Errorf("%s: plugin stage tree\n%v\nwant\n%v", abi, slices.Sorted(maps.Keys(stage)), slices.Sorted(maps.Keys(want)))
	}
}

func mustJSON(t *testing.T, v any) string {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// checkPublicKey checks that entry, a mode and the content of a file, is the public part of the
// builds' signing key in the PEM form pkg reads, readable by all.
func checkPublicKey(t *testing.T, abi, entry string) {
	t.Helper()
	data, ok := strings.CutPrefix(entry, "-rw-r--r-- ")
	block, rest := pem.Decode([]byte(data))
	if !ok || block == nil || block.Type != "PUBLIC KEY" || len(rest) != 0 {
		t.Errorf("%s: the public key is no PUBLIC KEY readable by all: %q", abi, entry)
		return
	}
	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	key, _ := repoKey()
	if rsaPub, ok := pub.(*rsa.PublicKey); err != nil || !ok || !rsaPub.Equal(&key.PublicKey) {
		t.Errorf("%s: the public key is not the signing key's: %v", abi, err)
	}
}

// Each refusal comes before the build touches the output directory, so a failed build keeps the
// repository of the last one.
func TestBuildPkgRefusesBadInput(t *testing.T) {
	type refusal struct {
		env []string
		msg string // what the build has to say, if the case checks it
	}
	var cases []refusal
	for _, version := range []string{"v0.47.0", "0.47.0-beta.1", "0.47.0_1", "0.47,1", "0.47.0 ", "0.47.ä", ""} {
		// Under de_DE.UTF-8 bash's [A-Za-z] also matches letters like ä.
		cases = append(cases, refusal{env: []string{"VERSION=" + version, "LC_ALL=de_DE.UTF-8"}})
	}
	for _, input := range []string{"PKG_REPO_KEY", "AGENT_BINARY", "FRPC_BINARY"} {
		cases = append(cases, refusal{env: []string{"VERSION=0.47.0", input + "=" + filepath.Join(t.TempDir(), "missing")}})
	}
	// pkg repo signs with an RSA key alone; the plugin would ship no public key for another.
	ec, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"key\n", pemKey(t, ec)} {
		path := filepath.Join(t.TempDir(), "key.pem")
		writeFile(t, path, key, 0o600)
		cases = append(cases, refusal{[]string{"VERSION=0.47.0", "PKG_REPO_KEY=" + path}, "is no RSA private key"})
	}
	for _, c := range cases {
		env := c.env
		b := newPkgBuild(t)
		out, err := b.run(env...)
		if err == nil {
			t.Errorf("%q: build-pkg.sh succeeded\n%s", env, out)
		}
		if !strings.Contains(string(out), c.msg) {
			t.Errorf("%q: output lacks %q:\n%s", env, c.msg, out)
		}
		if calls := b.calls(t); calls != nil {
			t.Errorf("%q: pkg called: %q", env, calls)
		}
		if !exists(t, filepath.Join(b.out, "freebsd/FreeBSD:14:amd64/All/stale.pkg")) {
			t.Errorf("%q: output directory changed before the check", env)
		}
	}
}
