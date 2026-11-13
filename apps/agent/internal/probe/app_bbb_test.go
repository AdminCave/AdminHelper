// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"context"
	"crypto/sha1" //nolint:gosec // bbb-web may allow it
	"crypto/sha256"
	"crypto/sha512"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

// stubRecordingDir points the recordings view at a fresh recording directory with an empty status
// directory and returns it.
func stubRecordingDir(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "status"), 0o755); err != nil {
		t.Fatal(err)
	}
	old := bbbRecordingDir
	bbbRecordingDir = root
	t.Cleanup(func() { bbbRecordingDir = old })
	return root
}

// failMarker writes the file name into status/<step> of root, modified at mod.
func failMarker(t *testing.T, root, step, name string, mod time.Time) {
	t.Helper()
	dir := filepath.Join(root, "status", step)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("secret log line"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, mod, mod); err != nil {
		t.Fatal(err)
	}
}

func TestTheRecordingsViewCountsTheFailMarkersOfEachStep(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	root := stubRecordingDir(t)
	id := "6e35e3b2778883f5db637d7a5dba0a427f692e91-1700000000000"
	failMarker(t, root, "archived", id+".done", at.Add(-48*time.Hour))
	failMarker(t, root, "archived", "a-1.fail", at.Add(-5*time.Hour))
	failMarker(t, root, "sanity", "b-2.fail", at.Add(-4*time.Hour))
	failMarker(t, root, "sanity", "c-3.fail", at.Add(-3*time.Hour))
	failMarker(t, root, "processed", id+"-presentation.done", at.Add(-time.Hour))
	failMarker(t, root, "processed", "d-4-presentation.fail", at.Add(-90*time.Minute))
	failMarker(t, root, "published", "e-5-video.fail", at.Add(-2*time.Hour))
	failMarker(t, root, "published", id+"-presentation.done", at.Add(-time.Hour))
	failMarker(t, root, "recorded", "f-6.fail", at.Add(-time.Minute)) // no step of the view
	if err := os.Mkdir(filepath.Join(root, "status", "sanity", "g-7.fail"), 0o755); err != nil {
		t.Fatal(err)
	}
	// Windows lets only privileged users link; without the link the count is the same.
	sanity := filepath.Join(root, "status", "sanity")
	err := os.Symlink(filepath.Join(sanity, "b-2.fail"), filepath.Join(sanity, "h-8.fail"))
	if err != nil && runtime.GOOS != "windows" {
		t.Fatal(err)
	}
	got, err := bbbRecordings(context.Background(), Target{Kind: kindUnit, Name: "bbb-web.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"failed": 5, "archive_failed": 1, "sanity_failed": 2, "process_failed": 1, "publish_failed": 1,
		"newest_fail_age_s": 5400,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v (only regular files *.fail of the four steps)", got, want)
	}
}

func TestTheRecordingsViewHasNoAgeWithoutAFailure(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	root := stubRecordingDir(t)
	failMarker(t, root, "archived", "a-1.done", at.Add(-time.Hour))
	got, err := bbbRecordings(context.Background(), Target{})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"failed": 0, "archive_failed": 0, "sanity_failed": 0, "process_failed": 0, "publish_failed": 0}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v", got, want)
	}
}

func TestTheRecordingsViewIsUnsupportedWithoutAStatusDirectory(t *testing.T) {
	old := bbbRecordingDir
	bbbRecordingDir = filepath.Join(t.TempDir(), "recording")
	t.Cleanup(func() { bbbRecordingDir = old })
	if _, err := bbbRecordings(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	// A file where the directory belongs is no BigBlueButton either.
	if err := os.MkdirAll(bbbRecordingDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(bbbRecordingDir, "status"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := bbbRecordings(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheRecordingsViewStopsAtTheEntryCap(t *testing.T) {
	root := stubRecordingDir(t)
	dir := filepath.Join(root, "status", "processed")
	if err := os.Mkdir(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	for i := range 3 {
		if err := os.WriteFile(filepath.Join(dir, strings.Repeat("x", i+1)+".fail"), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if got, _, err := countFailMarkers(context.Background(), dir, 3); err != nil || got != 3 {
		t.Fatalf("countFailMarkers = %d, %v; want 3 at the cap", got, err)
	}
	n, _, err := countFailMarkers(context.Background(), dir, 2)
	if err == nil || n != 0 || !strings.Contains(err.Error(), "more than 2 entries") {
		t.Errorf("over the cap: %d, %v; want an error and no count", n, err)
	}
}

func TestTheRecordingsViewFailsWithoutNamingPathOrContent(t *testing.T) {
	root := stubRecordingDir(t)
	// A file where a step's directory belongs opens but cannot be listed, on every platform.
	if err := os.WriteFile(filepath.Join(root, "status", "processed"), []byte("salt-0123456789abcdef"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := bbbRecordings(context.Background(), Target{})
	if err == nil || errors.Is(err, ErrUnsupported) || errors.Is(err, ErrInvalid) {
		t.Fatalf("error %v, want a plain error", err)
	}
	res := Run(context.Background(), appProbe("bbb_recordings", unitTarget("bbb-web.service")), time.Now(), nil)
	if res.Status != StatusError {
		t.Errorf("status %s, want error", res.Status)
	}
	for _, text := range []string{err.Error(), res.Error} {
		if strings.Contains(text, root) || strings.Contains(text, "salt-0123456789abcdef") {
			t.Errorf("error %q names the path or the content", text)
		}
	}
}

func TestTheRecordingsViewStopsWhenTheContextEnds(t *testing.T) {
	root := stubRecordingDir(t)
	failMarker(t, root, "sanity", "a-1.fail", time.Now())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := bbbRecordings(ctx, Target{}); !errors.Is(err, context.Canceled) {
		t.Errorf("error %v, want context.Canceled", err)
	}
}

// testSalt is the API secret of the BigBlueButton the meetings tests make up.
const testSalt = "unit-test-salt-of-bbb"

// stubBBBProperties points the meetings view at a fresh pair of properties files: contents maps the
// index in bbbPropertyFiles (0 the overrides, 1 the packaged defaults) to the file's content; an
// index without content has no file.
func stubBBBProperties(t *testing.T, contents map[int]string) {
	t.Helper()
	dir := t.TempDir()
	old := bbbPropertyFiles
	bbbPropertyFiles = []string{filepath.Join(dir, "bbb-web.properties"), filepath.Join(dir, "bigbluebutton.properties")}
	t.Cleanup(func() { bbbPropertyFiles = old })
	for i, c := range contents {
		if err := os.WriteFile(bbbPropertyFiles[i], []byte(c), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

// bbbAPI is a bbb-web on loopback the meetings view is pointed at; it answers every request with
// status and answer and keeps the request URIs.
type bbbAPI struct {
	mu   sync.Mutex
	uris []string
}

func (a *bbbAPI) requests() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return slices.Clone(a.uris)
}

func serveBBB(t *testing.T, status int, answer string) *bbbAPI {
	t.Helper()
	api := &bbbAPI{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		api.mu.Lock()
		api.uris = append(api.uris, r.URL.RequestURI())
		api.mu.Unlock()
		w.Header().Set("Content-Type", "text/xml")
		w.WriteHeader(status)
		_, _ = io.WriteString(w, answer)
	}))
	t.Cleanup(srv.Close)
	freshSnapshot(t) // the guard is to see the listener just started
	stubBBBEndpoint(t, portOf(t, srv.Listener.Addr().String()))
	return api
}

func stubBBBEndpoint(t *testing.T, port int) {
	t.Helper()
	old := bbbEndpoint
	bbbEndpoint = func(context.Context, Target) (endpoint, error) {
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(port)}, nil
	}
	t.Cleanup(func() { bbbEndpoint = old })
}

// checksumOf is the checksum bbb-web expects of getMeetings with salt in algorithm h.
func checksumOf(h hash.Hash, salt string) string {
	h.Write([]byte("getMeetings" + salt))
	return hex.EncodeToString(h.Sum(nil))
}

func bbbWeb() Target { return Target{Kind: kindUnit, Name: "bbb-web.service", PortHint: 8090} }

// bbbMeetingsAnswer has the form of bbb-web's get-meetings.ftlx: three meetings, one a breakout room,
// with names, passwords, attendees, custom data and metadata; some of the latter two carry the names
// of counted elements.
const bbbMeetingsAnswer = `<response>
<returncode>SUCCESS</returncode>
<meetings>
<meeting>
<meetingName>Board of Directors</meetingName><meetingID>mtg-ext-4711</meetingID>
<internalMeetingID>6e35e3b2778883f5db637d7a5dba0a427f692e91-1700000000000</internalMeetingID>
<createTime>1700000000000</createTime><createDate>Mon Nov 13 09:00:00 UTC 2026</createDate>
<voiceBridge>70123</voiceBridge><dialNumber>613-555-1234</dialNumber>
<attendeePW>ap-hunter2</attendeePW><moderatorPW>mp-hunter3</moderatorPW>
<running>true</running><duration>0</duration><hasUserJoined>true</hasUserJoined><recording>true</recording>
<hasBeenForciblyEnded>false</hasBeenForciblyEnded><startTime>1700000000100</startTime><endTime>0</endTime>
<participantCount>3</participantCount><listenerCount>1</listenerCount>
<voiceParticipantCount>2</voiceParticipantCount><videoCount>1</videoCount><maxUsers>0</maxUsers>
<moderatorCount>1</moderatorCount>
<attendees><attendee><userID>u-0815</userID><fullName>Erika Mustermann</fullName><role>MODERATOR</role>
<isPresenter>true</isPresenter><isListeningOnly>false</isListeningOnly><hasJoinedVoice>true</hasJoinedVoice>
<hasVideo>true</hasVideo><clientType>HTML5</clientType>
<customdata><running>true</running><participantCount>40</participantCount></customdata></attendee></attendees>
<metadata><bbb-origin-server-name>greenlight-room-xyz</bbb-origin-server-name><videoCount>50</videoCount></metadata>
<isBreakout>false</isBreakout>
<breakoutRooms><breakout>breakout-id-1</breakout></breakoutRooms>
</meeting>
<meeting>
<meetingName>Board of Directors (Room 1)</meetingName><meetingID>breakout-id-1</meetingID>
<attendeePW>ap-hunter2</attendeePW><moderatorPW>mp-hunter3</moderatorPW>
<running>true</running><recording>false</recording>
<participantCount>2</participantCount><listenerCount>0</listenerCount>
<voiceParticipantCount>2</voiceParticipantCount><videoCount>0</videoCount>
<attendees></attendees><metadata></metadata>
<isBreakout>true</isBreakout><parentMeetingID>mtg-ext-4711</parentMeetingID><sequence>1</sequence>
<freeJoin>false</freeJoin>
</meeting>
<meeting>
<meetingName>Elternabend 5b</meetingName><meetingID>mtg-ext-0042</meetingID>
<moderatorPW>mp-hunter3</moderatorPW>
<running>false</running><recording>true</recording>
<participantCount>0</participantCount><listenerCount>0</listenerCount>
<voiceParticipantCount>0</voiceParticipantCount><videoCount>0</videoCount>
<attendees/><metadata/><isBreakout>false</isBreakout>
</meeting>
</meetings>
</response>`

// bbbSecrets are what neither a value nor an error of the meetings view may hold.
func bbbSecrets(salt string) []string {
	return []string{
		salt, checksumOf(sha256.New(), salt), "Board of Directors", "mtg-ext-4711", "Elternabend", "ap-hunter2",
		"mp-hunter3", "u-0815", "Erika Mustermann", "greenlight-room-xyz", "breakout-id-1", "613-555-1234",
	}
}

func holdsNoSecret(t *testing.T, what, text string, secrets []string) {
	t.Helper()
	for _, s := range secrets {
		if strings.Contains(text, s) {
			t.Errorf("%s %q holds %q", what, text, s)
		}
	}
}

func zeroMeetings() map[string]any {
	return map[string]any{"meetings": 0, "running": 0, "participants": 0, "listeners": 0, "voice": 0, "video": 0, "recording": 0}
}

func TestTheMeetingsViewCountsOnlyTheNumbersOfEachMeeting(t *testing.T) {
	stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
	api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
	got, err := bbbMeetings(context.Background(), bbbWeb())
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"meetings": 3, "running": 2, "participants": 5, "listeners": 1, "voice": 4, "video": 1, "recording": 2}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v (no custom data, no metadata)", got, want)
	}
	holdsNoSecret(t, "values", fmt.Sprint(got), bbbSecrets(testSalt))
	uri := "/bigbluebutton/api/getMeetings?checksum=" + checksumOf(sha256.New(), testSalt)
	if reqs := api.requests(); !reflect.DeepEqual(reqs, []string{uri}) {
		t.Errorf("requests %v, want %v", reqs, []string{uri})
	}
}

func TestTheMeetingsViewReadsTheSaltAsBBBConfDoes(t *testing.T) {
	cases := map[string]struct {
		files map[int]string
		salt  string
	}{
		"the overrides first": {map[int]string{
			0: "# overrides\nsecuritySalt=etc-salt\n",
			1: "securitySalt=packaged-salt\nsupportedChecksumAlgorithms=sha1,sha256,sha384,sha512\n",
		}, "etc-salt"},
		"the packaged one without overrides": {map[int]string{1: "securitySalt=packaged-salt\n"}, "packaged-salt"},
		"the packaged one past an empty override": {map[int]string{
			0: "securitySalt=\n", 1: "securitySalt=packaged-salt\n",
		}, "packaged-salt"},
		"blanks around the separator and CRLF": {map[int]string{0: "  securitySalt = etc-salt\r\n"}, "etc-salt"},
		"not a key that only starts like it": {map[int]string{
			0: "securitySaltOld=old-salt\n#securitySalt=commented-salt\nsecuritySalt=etc-salt\n",
		}, "etc-salt"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			stubBBBProperties(t, c.files)
			api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
			if _, err := bbbMeetings(context.Background(), bbbWeb()); err != nil {
				t.Fatal(err)
			}
			uri := "/bigbluebutton/api/getMeetings?checksum=" + checksumOf(sha256.New(), c.salt)
			if reqs := api.requests(); !reflect.DeepEqual(reqs, []string{uri}) {
				t.Errorf("requests %v, want the checksum of salt %q", reqs, c.salt)
			}
		})
	}
}

func TestTheMeetingsViewTakesAnAlgorithmBBBAllows(t *testing.T) {
	cases := map[string]struct {
		allowed string // "" for no key
		hash    func() hash.Hash
	}{
		"no key":         {"", sha256.New},
		"the default":    {"sha1,sha256,sha384,sha512", sha256.New},
		"without sha256": {"sha1,sha384,sha512", sha512.New},
		"only sha384":    {"sha384", sha512.New384},
		"only sha1":      {"sha1", sha1.New},
		"blanks":         {" sha1, sha512 ", sha512.New},
		"upper case":     {"SHA256, sha1", sha1.New}, // String.contains of bbb-web minds the case
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			props := "securitySalt=" + testSalt + "\n"
			if c.allowed != "" {
				props += "supportedChecksumAlgorithms=" + c.allowed + "\n"
			}
			stubBBBProperties(t, map[int]string{0: props})
			api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
			if _, err := bbbMeetings(context.Background(), bbbWeb()); err != nil {
				t.Fatal(err)
			}
			uri := "/bigbluebutton/api/getMeetings?checksum=" + checksumOf(c.hash(), testSalt)
			if reqs := api.requests(); !reflect.DeepEqual(reqs, []string{uri}) {
				t.Errorf("requests %v, want %v", reqs, []string{uri})
			}
		})
	}
	t.Run("none the agent knows", func(t *testing.T) {
		stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\nsupportedChecksumAlgorithms=md5\n"})
		api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
		_, err := bbbMeetings(context.Background(), bbbWeb())
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("error %v, want an error", err)
		}
		if reqs := api.requests(); len(reqs) != 0 {
			t.Errorf("requests %v, want none", reqs)
		}
	})
}

func TestTheMeetingsViewIsUnsupportedWithoutASalt(t *testing.T) {
	cases := map[string]map[int]string{
		"no properties":        {},
		"no key":               {0: "bigbluebutton.web.serverURL=https://bbb.example.org\n", 1: "apiVersion=2.0\n"},
		"empty keys":           {0: "securitySalt=\n", 1: "securitySalt=   \n"},
		"only a commented one": {1: "# securitySalt=" + testSalt + "\n"},
	}
	for name, files := range cases {
		t.Run(name, func(t *testing.T) {
			stubBBBProperties(t, files)
			api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
			if _, err := bbbMeetings(context.Background(), bbbWeb()); !errors.Is(err, ErrUnsupported) {
				t.Errorf("error %v, want ErrUnsupported", err)
			}
			if reqs := api.requests(); len(reqs) != 0 {
				t.Errorf("requests %v, want none", reqs)
			}
		})
	}
}

func TestTheMeetingsViewCountsNoMeetingsAsZeros(t *testing.T) {
	answers := map[string]string{
		"success": `<response><returncode>SUCCESS</returncode><meetings/><messageKey>noMeetings</messageKey>` +
			`<message>no meetings were found on this server</message></response>`,
		"failed": `<response><returncode>FAILED</returncode><messageKey>noMeetings</messageKey>` +
			`<message>no meetings were found on this server</message></response>`,
	}
	for name, answer := range answers {
		t.Run(name, func(t *testing.T) {
			stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
			serveBBB(t, http.StatusOK, answer)
			got, err := bbbMeetings(context.Background(), bbbWeb())
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, zeroMeetings()) {
				t.Errorf("values %v, want %v", got, zeroMeetings())
			}
		})
	}
}

func TestTheMeetingsViewFailsWithoutLeakingAnything(t *testing.T) {
	secretText := "securitySalt=" + testSalt + " Board of Directors ap-hunter2 Erika Mustermann u-0815"
	big := "<response><returncode>SUCCESS</returncode><meetings>" +
		strings.Repeat("<meeting><meetingName>Board of Directors</meetingName><running>true</running></meeting>", 20000) +
		"</meetings></response>"
	cases := map[string]struct {
		status int
		answer string
		want   string // in the error
	}{
		"a wrong checksum": {http.StatusOK, `<response><returncode>FAILED</returncode><messageKey>checksumError</messageKey>` +
			`<message>Checksums do not match ap-hunter2</message></response>`, "checksumError"},
		"a list of errors": {http.StatusOK, `<response><returncode>FAILED</returncode><errors><error><key>checksumError</key>` +
			`<message>Erika Mustermann</message></error></errors></response>`, "checksumError"},
		"a messageKey of free text": {http.StatusOK, `<response><returncode>FAILED</returncode>` +
			`<messageKey>Board of Directors ap-hunter2</messageKey></response>`, "refuses"},
		"no returncode":    {http.StatusOK, `<response>` + secretText + `</response>`, "returncode"},
		"no XML":           {http.StatusOK, secretText, "XML"},
		"cut off":          {http.StatusOK, bbbMeetingsAnswer[:len(bbbMeetingsAnswer)/2], "XML"},
		"another root":     {http.StatusOK, `<html><body>` + secretText + `</body></html>`, "no API response"},
		"no count":         {http.StatusOK, `<response><returncode>SUCCESS</returncode><meetings><meeting><participantCount>Erika Mustermann</participantCount></meeting></meetings></response>`, "participantCount"},
		"a long value":     {http.StatusOK, `<response><returncode>SUCCESS ` + strings.Repeat("ap-hunter2 ", 10) + `</returncode></response>`, "longer"},
		"an HTTP error":    {http.StatusInternalServerError, secretText, "HTTP 500"},
		"a body too large": {http.StatusOK, big, "larger than"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
			serveBBB(t, c.status, c.answer)
			values, err := bbbMeetings(context.Background(), bbbWeb())
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("values %v, error %v; want an error naming %q", values, err, c.want)
			}
			holdsNoSecret(t, "error", err.Error(), bbbSecrets(testSalt))
			res := Run(context.Background(), appProbe("bbb_meetings", &Target{Kind: kindUnit, Name: "bbb-web.service", PortHint: 8090}), time.Now(), nil)
			if res.Status != StatusError {
				t.Errorf("status %s, want error", res.Status)
			}
			holdsNoSecret(t, "error of Run", res.Error, bbbSecrets(testSalt))
		})
	}
	t.Run("bbb-web down", func(t *testing.T) {
		stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
		srv := httptest.NewServer(http.NotFoundHandler())
		port := portOf(t, srv.Listener.Addr().String())
		srv.Close()
		freshSnapshot(t)
		stubBBBEndpoint(t, port)
		_, err := bbbMeetings(context.Background(), bbbWeb())
		if err == nil {
			t.Fatal("no error, want one")
		}
		holdsNoSecret(t, "error", err.Error(), bbbSecrets(testSalt))
	})
	t.Run("a port that echoes the request", func(t *testing.T) {
		// The HTTP client then quotes the request line, with the checksum, as a malformed status line.
		stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = ln.Close() })
		go func() {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				line, _ := bufio.NewReader(c).ReadString('\n')
				_, _ = io.WriteString(c, line)
				_ = c.Close()
			}
		}()
		freshSnapshot(t)
		stubBBBEndpoint(t, portOf(t, ln.Addr().String()))
		_, err = bbbMeetings(context.Background(), bbbWeb())
		if err == nil || !strings.Contains(err.Error(), "cannot be asked") {
			t.Fatalf("error %v, want bbb-web cannot be asked", err)
		}
		holdsNoSecret(t, "error", err.Error(), bbbSecrets(testSalt))
		res := Run(context.Background(), appProbe("bbb_meetings", &Target{Kind: kindUnit, Name: "bbb-web.service", PortHint: 8090}), time.Now(), nil)
		if res.Status != StatusError {
			t.Errorf("status %s, want error", res.Status)
		}
		holdsNoSecret(t, "error of Run", res.Error, bbbSecrets(testSalt))
	})
	t.Run("an unreadable override", func(t *testing.T) {
		stubBBBProperties(t, map[int]string{1: "securitySalt=" + testSalt + "\n"})
		if err := os.Mkdir(bbbPropertyFiles[0], 0o700); err != nil { // opens, but cannot be read
			t.Fatal(err)
		}
		_, err := bbbMeetings(context.Background(), bbbWeb())
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Fatalf("error %v, want an error", err)
		}
		holdsNoSecret(t, "error", err.Error(), append(bbbSecrets(testSalt), bbbPropertyFiles[0]))
	})
}

func TestTheMeetingsViewAsksOnlyBBBWeb(t *testing.T) {
	stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
	api := serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
	other := Target{Kind: kindUnit, Name: "nginx.service", PortHint: 8090}
	if _, err := bbbMeetings(context.Background(), other); !errors.Is(err, ErrInvalid) {
		t.Errorf("error %v, want ErrInvalid", err)
	}
	if reqs := api.requests(); len(reqs) != 0 {
		t.Errorf("requests %v, want none: the checksum goes to bbb-web alone", reqs)
	}
}

func TestTheMeetingsViewRunsThroughRunWithOnlyTheAskedFields(t *testing.T) {
	stubBBBProperties(t, map[int]string{0: "securitySalt=" + testSalt + "\n"})
	serveBBB(t, http.StatusOK, bbbMeetingsAnswer)
	res := Run(context.Background(), appProbe("bbb_meetings", &Target{Kind: kindUnit, Name: "bbb-web.service", PortHint: 8090}, "participants", "running"), time.Now(), nil)
	if res.Status != StatusOK {
		t.Fatalf("status %s (%s), want ok", res.Status, res.Error)
	}
	if want := map[string]any{"participants": 5, "running": 2}; !reflect.DeepEqual(res.Values, want) {
		t.Errorf("values %v, want %v", res.Values, want)
	}
}
