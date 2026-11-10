// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

// Package opnsense holds the tests of the OPNsense plugin os-adminhelper, whose source tree src/
// is laid out as in OPNsense's plugin repository. The dev box has neither PHP nor configd: these
// tests check the tree's structure and its names against the agent's, and run reconfigure.sh
// against stubs; PHP, configd and the template run natively on the OPNsense box.
package opnsense

import (
	"encoding/xml"
	"errors"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"testing"
)

const (
	src         = "src"
	controllers = src + "/opnsense/mvc/app/controllers/OPNsense/AdminHelper"
	models      = src + "/opnsense/mvc/app/models/OPNsense/AdminHelper"
	view        = src + "/opnsense/mvc/app/views/OPNsense/AdminHelper/general.volt"
	actions     = src + "/opnsense/service/conf/actions.d/actions_adminhelper.conf"
	templates   = src + "/opnsense/service/templates/OPNsense/AdminHelper"
	scripts     = src + "/opnsense/scripts/OPNsense/AdminHelper"
	inc         = src + "/etc/inc/plugins.inc.d/adminhelper.inc"
	servicePath = "/usr/sbin/service"
)

func read(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// goValues returns the string constants and variables of a Go file by name and, for each
// function, the last string literal in its body (the path it returns).
func goValues(t *testing.T, path string) map[string]string {
	t.Helper()
	f, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
	if err != nil {
		t.Fatal(err)
	}
	values := map[string]string{}
	str := func(e ast.Expr) (string, bool) {
		lit, ok := e.(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return "", false
		}
		s, err := strconv.Unquote(lit.Value)
		return s, err == nil
	}
	for _, decl := range f.Decls {
		switch d := decl.(type) {
		case *ast.GenDecl:
			for _, spec := range d.Specs {
				vs, ok := spec.(*ast.ValueSpec)
				if !ok {
					continue
				}
				for i, name := range vs.Names {
					if i < len(vs.Values) {
						if s, ok := str(vs.Values[i]); ok {
							values[name.Name] = s
						}
					}
				}
			}
		case *ast.FuncDecl:
			ast.Inspect(d.Body, func(n ast.Node) bool {
				if e, ok := n.(ast.Expr); ok {
					if s, ok := str(e); ok {
						values[d.Name.Name] = s
					}
				}
				return true
			})
		}
	}
	return values
}

// agentNames are the agent's names and paths on FreeBSD that the plugin uses, read from the
// agent's source.
type agentNames struct {
	rcName, childPid, agent, cron                    string
	etc, frpcTOML, frpConf, monitorConf, reportState string
}

func readAgentNames(t *testing.T) agentNames {
	t.Helper()
	rcd := goValues(t, "../internal/frpc/rcd.go")
	svc := goValues(t, "../internal/service/service_freebsd.go")
	dirs := goValues(t, "../internal/config/paths_freebsd.go")
	files := goValues(t, "../internal/config/paths.go")
	n := agentNames{
		rcName:      rcd["rcName"],
		childPid:    rcd["rcChildPidFile"],
		agent:       svc["agentBinary"],
		cron:        svc["cronFile"],
		etc:         dirs["MonitorDir"],
		frpcTOML:    dirs["FrpDir"] + "/" + files["FrpConfigFile"],
		frpConf:     dirs["FrpDir"] + "/" + files["FrpAdminHelperConf"],
		monitorConf: dirs["MonitorDir"] + "/" + files["MonitorConfFile"],
		reportState: dirs["MonitorDir"] + "/" + files["MonitorReportStateFile"],
	}
	if n.rcName == "" {
		t.Fatal("rcName not found in rcd.go")
	}
	for _, v := range []string{n.childPid, n.agent, n.cron, n.etc} {
		if !strings.HasPrefix(v, "/") {
			t.Fatalf("a path of the agent was not found: %+v", n)
		}
	}
	// The plugin writes the frp directory as $etc/frp.
	if dirs["FrpDir"] != n.etc+"/frp" {
		t.Fatalf("FrpDir %q is not MonitorDir/frp (%q)", dirs["FrpDir"], n.etc)
	}
	return n
}

func TestEveryXMLFileIsWellFormed(t *testing.T) {
	var found int
	err := filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || filepath.Ext(path) != ".xml" {
			return err
		}
		found++
		dec := xml.NewDecoder(strings.NewReader(read(t, path)))
		for {
			_, err := dec.Token()
			if errors.Is(err, io.EOF) {
				return nil
			}
			if err != nil {
				t.Errorf("%s: %v", path, err)
				return nil
			}
		}
	})
	if err != nil || found != 4 {
		t.Fatalf("walking %s: %v, %d XML files, want 4", src, err, found)
	}
}

type model struct {
	Mount string `xml:"mount"`
	Items struct {
		Fields []struct{ XMLName xml.Name } `xml:",any"`
	} `xml:"items"`
}

type form struct {
	Fields []struct {
		ID string `xml:"id"`
	} `xml:"field"`
}

type acl struct {
	Pages []struct {
		Patterns []string `xml:"patterns>pattern"`
	} `xml:",any"`
}

type menu struct {
	Sections []struct {
		Items []struct {
			URL string `xml:"url,attr"`
		} `xml:",any"`
	} `xml:",any"`
}

func unmarshal(t *testing.T, path string, v any) {
	t.Helper()
	if err := xml.Unmarshal([]byte(read(t, path)), v); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
}

func TestTheFormShowsTheFieldsOfTheModel(t *testing.T) {
	var m model
	unmarshal(t, models+"/General.xml", &m)
	if m.Mount != "//OPNsense/AdminHelper" {
		t.Errorf("model mount %q", m.Mount)
	}
	var items []string
	for _, f := range m.Items.Fields {
		items = append(items, f.XMLName.Local)
	}
	var f form
	unmarshal(t, controllers+"/forms/general.xml", &f)
	if len(f.Fields) == 0 {
		t.Fatal("the form has no field")
	}
	for _, field := range f.Fields {
		item, ok := strings.CutPrefix(field.ID, "general.")
		if !ok || !slices.Contains(items, item) {
			t.Errorf("form field %q is no item of the model (%v)", field.ID, items)
		}
	}
	for _, want := range []string{"$internalModelName = 'general'", `$internalModelClass = 'OPNsense\AdminHelper\General'`} {
		if !strings.Contains(read(t, controllers+"/Api/GeneralController.php"), want) {
			t.Errorf("Api/GeneralController.php lacks %s", want)
		}
	}
	page := read(t, controllers+"/GeneralController.php")
	for _, want := range []string{"pick('OPNsense/AdminHelper/general')", "getForm('general')"} {
		if !strings.Contains(page, want) {
			t.Errorf("GeneralController.php lacks %s", want)
		}
	}
}

// routes are the paths of the plugin's controllers, ui/adminhelper/<name>/ and
// api/adminhelper/<name>/, each with the source of its controller.
func routes(t *testing.T) map[string]string {
	t.Helper()
	out := map[string]string{}
	for prefix, dir := range map[string]string{"ui": controllers, "api": controllers + "/Api"} {
		paths, err := filepath.Glob(dir + "/*Controller.php")
		if err != nil || len(paths) == 0 {
			t.Fatalf("no controller in %s: %v", dir, err)
		}
		for _, p := range paths {
			name := strings.ToLower(strings.TrimSuffix(filepath.Base(p), "Controller.php"))
			out[prefix+"/adminhelper/"+name+"/"] = read(t, p)
		}
	}
	return out
}

func TestTheACLCoversEveryControllerAndTheMenu(t *testing.T) {
	var a acl
	unmarshal(t, models+"/ACL/ACL.xml", &a)
	var patterns []string
	for _, p := range a.Pages {
		patterns = append(patterns, p.Patterns...)
	}
	covered := func(path string) bool {
		for _, p := range patterns {
			if prefix, ok := strings.CutSuffix(p, "*"); ok && strings.HasPrefix(path, prefix) || p == path {
				return true
			}
		}
		return false
	}
	r := routes(t)
	if len(r) != 3 {
		t.Errorf("controllers %v, want the page, general and service", slices.Sorted(maps.Keys(r)))
	}
	for route := range r {
		if !covered(route + "index") {
			t.Errorf("no ACL pattern of %v covers %s", patterns, route)
		}
	}

	var m menu
	unmarshal(t, models+"/Menu/Menu.xml", &m)
	var urls []string
	for _, s := range m.Sections {
		for _, item := range s.Items {
			urls = append(urls, item.URL)
		}
	}
	if len(urls) != 1 {
		t.Fatalf("menu urls %v, want one", urls)
	}
	path := strings.TrimPrefix(urls[0], "/")
	route, action, _ := strings.Cut(path, "/general/")
	if src, ok := r[route+"/general/"]; !ok || !covered(path) || !strings.Contains(src, "function "+action+"Action(") {
		t.Errorf("the menu's %s reaches no page action the ACL allows", urls[0])
	}
}

// baseActions are the API actions the controllers inherit from OPNsense's base classes.
var baseActions = []string{"get", "set", "status", "start", "stop", "restart", "reconfigure"}

func TestThePageCallsActionsTheControllersHave(t *testing.T) {
	r := routes(t)
	page := read(t, view)
	calls := regexp.MustCompile(`"/(api/adminhelper/[a-z]+/)([a-z]+)"`).FindAllStringSubmatch(page, -1)
	if len(calls) < 4 {
		t.Fatalf("the page calls %v, want get, set, reconfigure and info", calls)
	}
	for _, c := range calls {
		src, ok := r[c[1]]
		if !ok || !slices.Contains(baseActions, c[2]) && !strings.Contains(src, "function "+c[2]+"Action(") {
			t.Errorf("the page calls /%s%s, which no controller has", c[1], c[2])
		}
	}
	// Every field the page shows is one info.php reports.
	info := read(t, scripts+"/info.php")
	for _, m := range regexp.MustCompile(`id="info_([a-z_]+)"`).FindAllStringSubmatch(page, -1) {
		if !strings.Contains(info, "'"+m[1]+"' =>") {
			t.Errorf("the page shows %s, which info.php does not report", m[1])
		}
	}
}

// configdActions reads an actions conf: its sections with their keys.
func configdActions(t *testing.T) map[string]map[string]string {
	t.Helper()
	out := map[string]map[string]string{}
	var section map[string]string
	for i, line := range strings.Split(read(t, actions), "\n") {
		line = strings.TrimSpace(line)
		switch {
		case line == "" || strings.HasPrefix(line, "#"):
		case strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]"):
			section = map[string]string{}
			out[line[1:len(line)-1]] = section
		default:
			key, value, ok := strings.Cut(line, ":")
			if !ok || section == nil {
				t.Fatalf("%s:%d: %q is neither a section nor a key", actions, i+1, line)
			}
			section[strings.TrimSpace(key)] = strings.TrimSpace(value)
		}
	}
	return out
}

func TestEveryConfigdActionIsComplete(t *testing.T) {
	n := readAgentNames(t)
	acts := configdActions(t)
	want := []string{"info", "reconfigure", "restart", "start", "status", "stop"}
	if got := slices.Sorted(maps.Keys(acts)); !slices.Equal(got, want) {
		t.Errorf("actions %v, want %v", got, want)
	}
	for name, a := range acts {
		for _, key := range []string{"command", "type", "message"} {
			if a[key] == "" {
				t.Errorf("action %s has no %s", name, key)
			}
		}
		if _, ok := a["parameters"]; !ok {
			t.Errorf("action %s has no parameters line", name)
		}
	}
	for name, verb := range map[string]string{"start": "start", "stop": "faststop", "restart": "restart", "status": "onestatus"} {
		if got := acts[name]["command"]; !strings.HasPrefix(got, servicePath+" "+n.rcName+" "+verb) {
			t.Errorf("action %s runs %q, want %s %s %s", name, got, servicePath, n.rcName, verb)
		}
	}
	// The switch reaches reconfigure.sh as one quoted argument; nothing else takes one.
	for name, a := range acts {
		if (a["parameters"] != "") != (name == "reconfigure") {
			t.Errorf("action %s takes parameters %q", name, a["parameters"])
		}
	}
	for _, name := range []string{"reconfigure", "info"} {
		script := strings.TrimPrefix(acts[name]["command"], "/usr/local/")
		st, err := os.Stat(filepath.Join(src, script))
		if err != nil || st.Mode()&0o111 == 0 {
			t.Errorf("action %s runs %s, which is no executable of the plugin: %v", name, acts[name]["command"], err)
		}
	}
	if acts["info"]["type"] != "script_output" || acts["status"]["type"] != "script_output" {
		t.Error("info and status have to return their output")
	}
}

func TestTheServicesAndTheTemplateUseTheNamesOfTheAgent(t *testing.T) {
	n := readAgentNames(t)
	plugin := read(t, inc)
	for _, want := range []string{
		"'name' => '" + n.rcName + "'",
		"'pidfile' => '" + n.childPid + "'",
		"file_exists('" + n.frpcTOML + "')",
		"'start' => ['adminhelper start']",
		"'stop' => ['adminhelper stop']",
		"'restart' => ['adminhelper restart']",
	} {
		if !strings.Contains(plugin, want) {
			t.Errorf("adminhelper.inc lacks %s", want)
		}
	}

	var targets []string
	for _, line := range strings.Split(read(t, templates+"/+TARGETS"), "\n") {
		if line = strings.TrimSpace(line); line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		source, target, ok := strings.Cut(line, ":")
		if !ok {
			t.Fatalf("+TARGETS line %q", line)
		}
		if _, err := os.Stat(filepath.Join(templates, source)); err != nil {
			t.Errorf("+TARGETS names %s, which is no template: %v", source, err)
		}
		targets = append(targets, target)
	}
	if !slices.Equal(targets, []string{"/etc/rc.conf.d/" + n.rcName}) {
		t.Errorf("+TARGETS writes %v, want only /etc/rc.conf.d/%s", targets, n.rcName)
	}

	tmpl := read(t, templates+"/"+n.rcName)
	for _, want := range []string{
		"helpers.file_exists('" + n.frpcTOML + "')",
		n.rcName + `_enable="YES"`,
		n.rcName + `_enable="NO"`,
		"OPNsense.AdminHelper.enabled == '1'",
	} {
		if !strings.Contains(tmpl, want) {
			t.Errorf("the template lacks %s", want)
		}
	}
	// The rc.d script of the agent waits for the same frpc.toml.
	if rc := read(t, "../freebsd/"+n.rcName); !strings.Contains(rc, `required_files="`+n.frpcTOML+`"`) {
		t.Errorf("the rc.d script does not require %s", n.frpcTOML)
	}
}

func TestInfoReadsTheAgentsFilesAndNoSecret(t *testing.T) {
	n := readAgentNames(t)
	info := strings.ReplaceAll(read(t, scripts+"/info.php"), "$etc", n.etc)
	for _, want := range []string{n.frpConf, n.monitorConf, n.frpcTOML, n.reportState, n.cron, n.agent + " version", servicePath + " " + n.rcName + " onestatus"} {
		if !strings.Contains(info, want) {
			t.Errorf("info.php does not read %s", want)
		}
	}
	// Of the keys of the agent's files it reads the URLs alone.
	keys := regexp.MustCompile(`'([A-Z][A-Z0-9_]+)'`).FindAllStringSubmatch(info, -1)
	for _, k := range keys {
		if k[1] != "ADMINHELPER_URL" && k[1] != "MONITOR_URL" {
			t.Errorf("info.php reads the key %s", k[1])
		}
	}
	if len(keys) != 2 {
		t.Errorf("info.php reads keys %v, want ADMINHELPER_URL and MONITOR_URL", keys)
	}
	for _, never := range []string{"API_KEY", "identity", "credentials", "token"} {
		if strings.Contains(strings.ToLower(info), strings.ToLower(never)) {
			t.Errorf("info.php mentions %s", never)
		}
	}
}

// host is an OPNsense box faked for reconfigure.sh: its root holds the agent's files, and stubs of
// service(8) and the agent log their calls in one file, in order. The client runs while the file
// running exists; a file fail makes the stub of the agent fail.
type host struct {
	root, state string
	n           agentNames
}

const serviceStub = `#!/bin/sh
echo "service $*" >> "$AH_STATE/calls"
case "$2" in
    onestatus) [ -f "$AH_STATE/running" ] ;;
    start) : > "$AH_STATE/running" ;;
    faststop) rm -f "$AH_STATE/running" ;;
    *) exit 1 ;;
esac
`

const agentStub = `#!/bin/sh
echo "agent $*" >> "$AH_STATE/calls"
[ -f "$AH_STATE/fail" ] && exit 1
case "$1 $2" in
    "service install") mkdir -p "${AH_CRON%/*}" && : > "$AH_CRON" ;;
    "service uninstall") rm -f "$AH_CRON" ;;
    *) exit 1 ;;
esac
`

func newHost(t *testing.T, files ...string) *host {
	t.Helper()
	h := &host{root: t.TempDir(), state: t.TempDir(), n: readAgentNames(t)}
	for _, f := range files {
		h.write(t, f, "")
	}
	return h
}

func (h *host) write(t *testing.T, path, data string) {
	t.Helper()
	p := filepath.Join(h.root, path)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(data), 0o755); err != nil {
		t.Fatal(err)
	}
}

func (h *host) exists(path string) bool {
	_, err := os.Stat(filepath.Join(h.root, path))
	return err == nil
}

// run runs reconfigure.sh with arg as configd does, its paths moved into the fake root, and returns
// its exit status and the calls it made.
func (h *host) run(t *testing.T, arg string) (int, []string) {
	t.Helper()
	h.write(t, servicePath, serviceStub)
	h.write(t, h.n.agent, agentStub)
	body := read(t, scripts+"/reconfigure.sh")
	moved := strings.NewReplacer(h.n.etc, "", h.n.agent, "", servicePath, "", "/dev/null", "")
	for _, line := range strings.Split(body, "\n") {
		if !strings.HasPrefix(strings.TrimSpace(line), "#") && regexp.MustCompile(`(^|[^A-Za-z0-9_.])/[A-Za-z]`).MatchString(moved.Replace(line)) {
			t.Fatalf("reconfigure.sh: %q names a path the test does not move", line)
		}
	}
	for _, p := range []string{h.n.etc, h.n.agent, servicePath} {
		body = strings.ReplaceAll(body, p, h.root+p)
	}
	_ = os.Remove(filepath.Join(h.state, "calls"))
	cmd := exec.Command("/bin/sh", "-c", body, "reconfigure.sh", arg)
	cmd.Env = append(os.Environ(), "AH_STATE="+h.state, "AH_CRON="+filepath.Join(h.root, h.n.cron))
	out, err := cmd.CombinedOutput()
	code := 0
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		code = exit.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(h.state, "calls"))
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	var calls []string
	if s := strings.TrimSpace(string(data)); s != "" {
		calls = strings.Split(s, "\n")
	}
	if code == 0 && len(out) != 0 {
		t.Errorf("reconfigure.sh %s printed %q", arg, out)
	}
	return code, calls
}

func (h *host) set(t *testing.T, name string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(h.state, name), nil, 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestReconfigureOnSchedulesTheAgentAndStartsTheTunnel(t *testing.T) {
	n := readAgentNames(t)
	install, onestatus, start := "agent service install", "service "+n.rcName+" onestatus", "service "+n.rcName+" start"
	cases := []struct {
		name    string
		files   []string
		running bool
		want    []string
	}{
		{"registered with a tunnel", []string{n.frpConf, n.frpcTOML}, false, []string{install, onestatus, start}},
		{"tunnel running", []string{n.frpConf, n.frpcTOML}, true, []string{install, onestatus}},
		{"monitoring alone", []string{n.monitorConf}, false, []string{install}},
		{"not registered", nil, false, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := newHost(t, c.files...)
			if c.running {
				h.set(t, "running")
			}
			code, calls := h.run(t, "on")
			if code != 0 || !slices.Equal(calls, c.want) {
				t.Errorf("on = %d, calls %q, want 0, %q", code, calls, c.want)
			}
			if registered := len(c.files) > 0; h.exists(n.cron) != registered {
				t.Errorf("cron entry %v, want %v", h.exists(n.cron), registered)
			}
		})
	}
}

func TestReconfigureOffRemovesTheScheduleBeforeItStopsTheTunnel(t *testing.T) {
	n := readAgentNames(t)
	h := newHost(t, n.frpConf, n.frpcTOML, n.cron)
	h.set(t, "running")
	code, calls := h.run(t, "off")
	want := []string{"agent service uninstall", "service " + n.rcName + " faststop"}
	if code != 0 || !slices.Equal(calls, want) {
		t.Errorf("off = %d, calls %q, want 0, %q", code, calls, want)
	}
	if h.exists(n.cron) {
		t.Error("the cron entry is still there")
	}
	if _, err := os.Stat(filepath.Join(h.state, "running")); err == nil {
		t.Error("the tunnel client still runs")
	}
	if !h.exists(n.frpConf) || !h.exists(n.frpcTOML) {
		t.Error("off removed the agent's files")
	}
}

func TestReconfigureFailsWhenTheAgentFails(t *testing.T) {
	n := readAgentNames(t)
	for arg, want := range map[string][]string{
		"on":  {"agent service install"},
		"off": {"agent service uninstall"},
	} {
		h := newHost(t, n.frpConf, n.frpcTOML)
		h.set(t, "fail")
		if code, calls := h.run(t, arg); code != 1 || !slices.Equal(calls, want) {
			t.Errorf("%s with a failing agent = %d, calls %q, want 1, %q", arg, code, calls, want)
		}
	}
}

func TestReconfigureRefusesAnyOtherArgument(t *testing.T) {
	n := readAgentNames(t)
	for _, arg := range []string{"", "ON", "on; off", "--help"} {
		h := newHost(t, n.frpConf, n.frpcTOML)
		if code, calls := h.run(t, arg); code != 64 || calls != nil {
			t.Errorf("reconfigure.sh %q = %d, calls %q, want 64 and none", arg, code, calls)
		}
	}
}
