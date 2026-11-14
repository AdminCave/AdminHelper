// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// backupNow is the clock of the backup views' tests, in local time as the logs write it.
var backupNow = time.Date(2026, 11, 14, 12, 0, 0, 0, time.Local)

// stubStatOnly makes statPath find exactly the paths in have.
func stubStatOnly(t *testing.T, have ...string) {
	t.Helper()
	old := statPath
	statPath = func(path string) (fs.FileInfo, error) {
		for _, h := range have {
			if h == path {
				return nil, nil
			}
		}
		return nil, fs.ErrNotExist
	}
	t.Cleanup(func() { statPath = old })
}

// backuppcAnswer has the form of `BackupPC_serverMesg status hosts` (checked against BackupPC 4.4.0):
// a host backed up, one whose last backup failed, one that did not answer the ping while a job runs,
// one never backed up, and a job of the server under a name with a leading space. The values of a
// list and a hash in a host are as BackupPC's source writes them (not seen).
var backuppcAnswer = `Got reply: %Status = ("pc-buchhaltung" => {"deadCnt" => 0,"state" => "Status_idle",` +
	`"lastGoodBackupTime" => ` + fmt.Sprint(backupNow.Add(-2*time.Hour).Unix()) + `,"type" => "full",` +
	`"userReq" => undef,"endTime" => 1794613900,"aliveCnt" => 1,"activeJob" => 0,"reason" => "Reason_backup_done",` +
	`"startTime" => 1794613800},` +
	`"srv-lager" => {"state" => "Status_idle","lastGoodBackupTime" => ` + fmt.Sprint(backupNow.Add(-50*time.Hour).Unix()) + `,` +
	`"reason" => "Reason_backup_failed","error" => "Unable to read 4 bytes: \"x\"","activeJob" => 0},` +
	`'nb-chef' => {'state' => 'Status_backup_in_progress','reason' => 'Reason_no_ping','activeJob' => 1,` +
	`'lastGoodBackupTime' => '` + fmt.Sprint(backupNow.Add(-3*time.Hour).Unix()) + `','xferPids' => [1201, 1202],'more' => {'a' => [ ], 'b' => {}}},` +
	"\n  \"neuer-host\" => {\"endTime\" => \"\",\"state\" => \"Status_idle\",\"activeJob\" => 0,\"userReq\" => undef},\n" +
	`" trashClean " => {"state" => "Status_idle","activeJob" => 1,"lastGoodBackupTime" => 1});` + "\n"

func TestBackupPCStatusCountsTheHosts(t *testing.T) {
	stubNow(t, backupNow)
	stubStatOnly(t, backuppcMesg[1])
	calls := stubTools(t, answer{out: backuppcAnswer})
	got, err := backuppcStatus(context.Background(), *unitTarget("backuppc.service"))
	want := map[string]any{
		"hosts": 4, "hosts_failed": 1, "hosts_no_ping": 1, "hosts_never_backed_up": 1, "jobs_active": 1,
		"backup_age_max_s": int64(50 * 3600),
	}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("backuppc_status = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "buchhaltung", "lager", "chef", "neuer-host", "Unable")
	wantCall := []string{"runuser", "-u", "backuppc", "--", backuppcMesg[1], "status", "hosts"}
	if len(*calls) != 1 || !reflect.DeepEqual((*calls)[0], wantCall) {
		t.Errorf("calls %q, want %q", *calls, wantCall)
	}
}

func TestBackupPCStatusWithoutHostsHasNoAge(t *testing.T) {
	stubStatOnly(t, backuppcMesg[0])
	stubTools(t, answer{out: "Got reply: %Status = ();\n"})
	got, err := backuppcStatus(context.Background(), *unitTarget("backuppc.service"))
	want := map[string]any{"hosts": 0, "hosts_failed": 0, "hosts_no_ping": 0, "hosts_never_backed_up": 0, "jobs_active": 0}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("backuppc_status = %v, %v; want %v", got, err, want)
	}
}

func TestBackupPCStatusWithoutBackupPCOrRunuser(t *testing.T) {
	stubStatOnly(t)
	calls := stubTools(t)
	if _, err := backuppcStatus(context.Background(), *unitTarget("backuppc.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("without BackupPC_serverMesg = %v, want unsupported", err)
	}
	if len(*calls) != 0 {
		t.Errorf("calls %q, want none", *calls)
	}
	stubStatOnly(t, backuppcMesg[0])
	stubTools(t, answer{err: &exec.Error{Name: "runuser", Err: exec.ErrNotFound}})
	if _, err := backuppcStatus(context.Background(), *unitTarget("backuppc.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("without runuser = %v, want unsupported", err)
	}
}

func TestBackupPCStatusRefusesAnAnswerOfAnotherForm(t *testing.T) {
	deep := strings.Repeat("[", maxPerlDepth+2) + strings.Repeat("]", maxPerlDepth+2)
	for name, out := range map[string]string{
		"wrong user":    "Wrong user: my userid is 0, instead of 101 (backuppc)\n",
		"empty":         "",
		"no close":      `Got reply: %Status = ("a" => {"state" => "x"}`,
		"open string":   `Got reply: %Status = ("a" => {"state" => "x});`,
		"bare host":     `Got reply: %Status = (a => 1);`,
		"no arrow":      `Got reply: %Status = ("a" {"state" => 1});`,
		"sign as value": `Got reply: %Status = ("a" => {"state" => ,});`,
		"trailing text": `Got reply: %Status = ();rm`,
		"too deep":      `Got reply: %Status = ("a" => {"x" => ` + deep + `});`,
	} {
		t.Run(name, func(t *testing.T) {
			stubStatOnly(t, backuppcMesg[0])
			stubTools(t, answer{out: out})
			_, err := backuppcStatus(context.Background(), *unitTarget("backuppc.service"))
			if !errors.Is(err, errBackupPCForm) {
				t.Errorf("answer %q = %v, want %v", out, err, errBackupPCForm)
			}
		})
	}
}

// urbackupServer stands in for UrBackup's web API: it answers each action from answers and keeps the
// method and query of every request.
type urbackupServer struct {
	mu       sync.Mutex
	requests []string
}

func serveUrBackup(t *testing.T, answers map[string]func(q map[string][]string) string) (*urbackupServer, int) {
	t.Helper()
	ub := &urbackupServer{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ub.mu.Lock()
		ub.requests = append(ub.requests, r.Method+" "+r.URL.RequestURI())
		ub.mu.Unlock()
		q := r.URL.Query()
		f := answers[q.Get("a")]
		if r.URL.Path != "/x" || f == nil {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, f(q))
	}))
	t.Cleanup(srv.Close)
	freshSnapshot(t)
	port := portOf(t, srv.Listener.Addr().String())
	old := urbackupEndpoint
	urbackupEndpoint = func(context.Context, Target) (endpoint, error) {
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(port)}, nil
	}
	t.Cleanup(func() { urbackupEndpoint = old })
	return ub, port
}

func (ub *urbackupServer) asked() []string {
	ub.mu.Lock()
	defer ub.mu.Unlock()
	return append([]string(nil), ub.requests...)
}

// urbackupStatusAnswer has the fields of action status as the author's wrapper reads them: a client
// backed up, one whose file backup failed and that was not seen for two days, one whose image backup
// failed, one with images not supported and file backups turned off, and one never backed up.
var urbackupStatusAnswer = fmt.Sprintf(`{"status":[`+
	`{"name":"pc-buchhaltung","id":1,"lastbackup":%d,"lastbackup_image":%d,"file_ok":true,"image_ok":true,"lastseen":%d,"online":true},`+
	`{"name":"srv-lager","id":2,"lastbackup":%d,"file_ok":false,"image_ok":true,"lastseen":%d,"online":false},`+
	`{"name":"nb-chef","id":3,"lastbackup":%d,"file_ok":true,"image_ok":false,"lastseen":%d},`+
	`{"name":"vm-linux","id":4,"lastbackup":"-","file_ok":false,"file_disabled":true,"image_ok":false,"image_not_supported":true,"lastseen":%d},`+
	`{"name":"neu","id":5,"lastbackup":0,"file_ok":true,"image_ok":true,"image_disabled":true,"lastseen":"-"}`+
	`],"nospc_stalled":false,"nospc_fatal":false,"database_error":true}`,
	backupNow.Add(-time.Hour).Unix(), backupNow.Add(-time.Hour).Unix(), backupNow.Add(-time.Minute).Unix(),
	backupNow.Add(-72*time.Hour).Unix(), backupNow.Add(-48*time.Hour).Unix(),
	backupNow.Add(-5*time.Hour).Unix(), backupNow.Add(-time.Minute).Unix(), backupNow.Add(-time.Minute).Unix())

var urbackupWant = map[string]any{
	"clients": 5, "clients_file_failed": 1, "clients_image_failed": 1, "clients_unseen_24h": 2,
	"file_backup_age_max_s": int64(72 * 3600), "nospc_fatal": false, "database_error": true,
}

func urbackupUnit(port int) Target {
	return Target{Kind: kindUnit, Name: "urbackupsrv.service", PortHint: port}
}

func TestUrBackupStatusAsTheAnonymousUser(t *testing.T) {
	stubNow(t, backupNow)
	ub, port := serveUrBackup(t, map[string]func(map[string][]string) string{
		"login":  func(map[string][]string) string { return `{"success":true,"session":"SeSs1"}` },
		"status": func(q map[string][]string) string { return urbackupStatusAnswer },
	})
	got, err := urbackupStatus(context.Background(), urbackupUnit(port), appCredential{})
	if err != nil || !reflect.DeepEqual(got, urbackupWant) {
		t.Fatalf("urbackup_status = %v, %v; want %v", got, err, urbackupWant)
	}
	noneOf(t, got, "buchhaltung", "lager", "chef", "SeSs1")
	if want := []string{"GET /x?a=login", "GET /x?a=status&ses=SeSs1"}; !reflect.DeepEqual(ub.asked(), want) {
		t.Errorf("asked %q, want %q", ub.asked(), want)
	}
}

func TestUrBackupStatusLogsInWithTheWebUser(t *testing.T) {
	// The hashes are Python's (hashlib.md5, hashlib.pbkdf2_hmac), as the author's wrapper makes them.
	for rounds, hash := range map[int]string{0: "f67c3de9f03cfc96311071e791b7c2aa", 10000: "e4b0503e5ddef98e992657c7d214d6ea"} {
		t.Run(fmt.Sprint(rounds), func(t *testing.T) {
			stubNow(t, backupNow)
			ub, port := serveUrBackup(t, map[string]func(map[string][]string) string{
				"login": func(q map[string][]string) string {
					if len(q["username"]) == 0 {
						return `{"success":false}`
					}
					return fmt.Sprintf(`{"success":%v}`, q["username"][0] == "monitor" && q["password"][0] == hash && q["ses"][0] == "SeSs2")
				},
				"salt": func(q map[string][]string) string {
					return fmt.Sprintf(`{"ses":"SeSs2","salt":"s4lTx","rnd":"rNd9q","pbkdf2_rounds":%d}`, rounds)
				},
				"status": func(map[string][]string) string { return urbackupStatusAnswer },
			})
			got, err := urbackupStatus(context.Background(), urbackupUnit(port), appCredential{use: useBasic, secret: "monitor:Geh31m!"})
			if err != nil || !reflect.DeepEqual(got, urbackupWant) {
				t.Fatalf("urbackup_status = %v, %v; want %v", got, err, urbackupWant)
			}
			asked := ub.asked()
			want := []string{"GET /x?a=login", "GET /x?a=salt&username=monitor",
				"GET /x?a=login&password=" + hash + "&ses=SeSs2&username=monitor", "GET /x?a=status&ses=SeSs2"}
			if !reflect.DeepEqual(asked, want) {
				t.Errorf("asked %q, want %q", asked, want)
			}
			if strings.Contains(strings.Join(asked, " "), "Geh31m") {
				t.Errorf("the password went to the server: %q", asked)
			}
		})
	}
}

func TestUrBackupStatusIsDeniedWithoutAUserItTakes(t *testing.T) {
	refuse := map[string]func(map[string][]string) string{
		"login":  func(map[string][]string) string { return `{"success":false}` },
		"salt":   func(map[string][]string) string { return `{"error":0}` },
		"status": func(map[string][]string) string { return urbackupStatusAnswer },
	}
	_, port := serveUrBackup(t, refuse)
	for name, c := range map[string]appCredential{
		"no credential": {},
		"unknown user":  {use: useBasic, secret: "wer:x"},
	} {
		_, err := urbackupStatus(context.Background(), urbackupUnit(port), c)
		if !errors.Is(err, ErrDenied) {
			t.Errorf("%s = %v, want denied", name, err)
		}
	}
	refuse["salt"] = func(map[string][]string) string { return `{"ses":"S","salt":"s","rnd":"r","pbkdf2_rounds":0}` }
	_, port = serveUrBackup(t, refuse)
	if _, err := urbackupStatus(context.Background(), urbackupUnit(port), appCredential{use: useBasic, secret: "monitor:falsch"}); !errors.Is(err, ErrDenied) {
		t.Errorf("a wrong password = %v, want denied", err)
	}
	if _, err := urbackupStatus(context.Background(), urbackupUnit(port), appCredential{use: useBasic, secret: "monitor"}); !errors.Is(err, ErrInvalid) {
		t.Errorf("a credential without password = %v, want invalid", err)
	}
}

func TestUrBackupStatusRefusesAnotherAnswer(t *testing.T) {
	for name, status := range map[string]string{
		"no status": `{"error":1}`,
		"no json":   `<html>`,
	} {
		_, port := serveUrBackup(t, map[string]func(map[string][]string) string{
			"login":  func(map[string][]string) string { return `{"success":true,"session":"S"}` },
			"status": func(map[string][]string) string { return status },
		})
		if _, err := urbackupStatus(context.Background(), urbackupUnit(port), appCredential{}); !errors.Is(err, errUrBackupForm) {
			t.Errorf("%s = %v, want %v", name, err, errUrBackupForm)
		}
	}
}

func TestUrBackupStatusTakesItsPortAndScheme(t *testing.T) {
	var asked Target
	old := urbackupEndpoint
	urbackupEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		asked = t
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: 35623}, nil
	}
	t.Cleanup(func() { urbackupEndpoint = old })
	if _, err := urbackupStatus(context.Background(), urbackupUnit(0), appCredential{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("another port alone = %v, want unsupported", err)
	}
	if asked.PortHint != urbackupPort {
		t.Errorf("resolved %+v, want port hint %d", asked, urbackupPort)
	}
	tg := urbackupUnit(0)
	tg.Scheme = "https"
	if _, err := urbackupStatus(context.Background(), tg, appCredential{}); !errors.Is(err, ErrInvalid) {
		t.Errorf("scheme https = %v, want invalid", err)
	}
}

// veeamAnswer is the assumed form of `veeamconfig session list` (not verified, see veeamSessions): a
// job whose last session failed after a success, one with a warning, one never successful and running,
// and a restore session, which has no job name.
var veeamAnswer = "Job name                  Type      ID                                      State    Started at        Finished at\n" +
	"Buchhaltung Server        Backup    {0b0e7a5e-1111-4a51-9f00-aaaaaaaaaaaa}  Success  2026-11-12 22:00  2026-11-12 22:10\n" +
	"Buchhaltung Server        Backup    {0b0e7a5e-2222-4a51-9f00-aaaaaaaaaaaa}  Failed   2026-11-13 22:00  2026-11-13 22:01\n" +
	"Lager                     Backup    {0b0e7a5e-3333-4a51-9f00-aaaaaaaaaaaa}  Warning  2026-11-14 01:00  2026-11-14 01:30\n" +
	"Lager                     Backup    {0b0e7a5e-4444-4a51-9f00-aaaaaaaaaaaa}  Success  2026-11-13 01:00  2026-11-13 01:30:00\n" +
	"Chef                      Backup    {0b0e7a5e-5555-4a51-9f00-aaaaaaaaaaaa}  Running  2026-11-14 11:00\n" +
	"                          Restore   {0b0e7a5e-6666-4a51-9f00-aaaaaaaaaaaa}  Failed   2026-11-14 09:00  2026-11-14 09:05\n" +
	"Total amount: 6\n"

func TestVeeamSessionsCountsTheJobs(t *testing.T) {
	stubNow(t, backupNow)
	calls := stubTools(t, answer{out: veeamAnswer})
	got, err := veeamSessions(context.Background(), *unitTarget("veeamservice.service"))
	want := map[string]any{"jobs": 3, "jobs_failed": 1, "jobs_warning": 1, "sessions_running": 1,
		"last_success_age_max_s": int64(backupNow.Sub(time.Date(2026, 11, 12, 22, 10, 0, 0, time.Local)) / time.Second)}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("veeam_sessions = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "Buchhaltung", "Lager", "Chef", "0b0e7a5e")
	if want := []string{"veeamconfig", "session", "list"}; len(*calls) != 1 || !reflect.DeepEqual((*calls)[0], want) {
		t.Errorf("calls %q, want %q", *calls, want)
	}
}

func TestVeeamSessionsRefusesAnotherForm(t *testing.T) {
	head := "Job name  Type    ID   State    Started at        Finished at\n"
	for name, out := range map[string]string{
		"no header":     "No sessions\n",
		"no state":      "Job name  Type  ID  Started at  Finished at\nTotal amount: 0\n",
		"no total":      head + "J         Backup  {1}  Success  2026-11-13 01:00  2026-11-13 01:30\n",
		"after total":   head + "Total amount: 0\nJ  Backup  {1}  Success  2026-11-13 01:00  2026-11-13 01:30\n",
		"unknown state": head + "J         Backup  {1}  Stopped  2026-11-13 01:00  2026-11-13 01:30\nTotal amount: 1\n",
		"no time":       head + "J         Backup  {1}  Success  gestern           heute\nTotal amount: 1\n",
	} {
		t.Run(name, func(t *testing.T) {
			stubTools(t, answer{out: out})
			if _, err := veeamSessions(context.Background(), *unitTarget("veeamservice.service")); err == nil {
				t.Errorf("answer %q passed", out)
			}
		})
	}
	stubTools(t, answer{out: head + "Total amount: 0\n"})
	got, err := veeamSessions(context.Background(), *unitTarget("veeamservice.service"))
	if want := map[string]any{"jobs": 0, "jobs_failed": 0, "jobs_warning": 0, "sessions_running": 0}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("no sessions = %v, %v; want %v", got, err, want)
	}
	stubTools(t, answer{err: &exec.Error{Name: "veeamconfig", Err: exec.ErrNotFound}})
	if _, err := veeamSessions(context.Background(), *unitTarget("veeamservice.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("without Veeam = %v, want unsupported", err)
	}
}

// rsnapshotHere writes an rsnapshot configuration with the settings into a directory of the test and
// points the view at it; it returns the directory.
func rsnapshotHere(t *testing.T, settings ...string) string {
	t.Helper()
	dir := t.TempDir()
	conf := "config_version\t1.2\nsnapshot_root\t/var/cache/rsnapshot/\n#logfile\t/var/log/old.log\n" +
		"logfile /var/log/with-spaces.log\n"
	for _, s := range settings {
		conf += strings.ReplaceAll(s, "<dir>", dir) + "\n"
	}
	path := filepath.Join(dir, "rsnapshot.conf")
	if err := os.WriteFile(path, []byte(conf), 0o600); err != nil {
		t.Fatal(err)
	}
	old := rsnapshotConfigs
	rsnapshotConfigs = []string{filepath.Join(dir, "absent.conf"), path}
	t.Cleanup(func() { rsnapshotConfigs = old })
	return dir
}

func TestTheBackupViewsAreRegistered(t *testing.T) {
	stubNow(t, backupNow)
	stubStatOnly(t, backuppcMesg[0])
	stubTools(t, answer{out: backuppcAnswer}, answer{out: veeamAnswer})
	res := Run(context.Background(), appProbe("backuppc_status", unitTarget("backuppc.service"), "hosts_failed"), time.Now(), nil)
	if res.Status != StatusOK || res.Values["hosts_failed"] != 1 {
		t.Errorf("backuppc_status: %s (%s) %v", res.Status, res.Error, res.Values)
	}
	res = Run(context.Background(), appProbe("veeam_sessions", unitTarget("veeamservice.service"), "jobs_failed"), time.Now(), nil)
	if res.Status != StatusOK || res.Values["jobs_failed"] != 1 {
		t.Errorf("veeam_sessions: %s (%s) %v", res.Status, res.Error, res.Values)
	}
	rsnapshotHere(t)
	if res := Run(context.Background(), hostProbe("rsnapshot", "last_status"), time.Now(), nil); res.Status != StatusUnsupported || !strings.Contains(res.Error, "logfile") {
		t.Errorf("rsnapshot: %s (%s), want unsupported for want of a log", res.Status, res.Error)
	}
	p := appProbe("urbackup_status", unitTarget("urbackupsrv.service"))
	p.Credential = &Credential{Ref: "u", Use: usePassword}
	if _, err := appSensor(context.Background(), p, "s3cr3t"); !errors.Is(err, ErrInvalid) {
		t.Errorf("urbackup_status with a password credential = %v, want ErrInvalid", err)
	}
}
