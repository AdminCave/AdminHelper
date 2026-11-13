// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/sha1" //nolint:gosec // one of the algorithms bbb-web may allow for its checksums
	"crypto/sha256"
	"crypto/sha512"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"fmt"
	"hash"
	"io"
	"io/fs"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
)

// bbbRecordingDir is where BigBlueButton keeps its recordings and the status of their processing
// (recording_dir in bigbluebutton.yml, the packages' default); tests point it elsewhere.
var bbbRecordingDir = "/var/bigbluebutton/recording"

// maxStatusEntries caps the entries the recordings view reads in one status directory: a .done
// marker stays there for every recording ever processed.
const maxStatusEntries = 500_000

// bbbFailSteps are the steps of the recording processing that leave a marker <id>.fail (archive,
// sanity) or <id>-<format>.fail (process, publish) in their status directory when they fail
// (record-and-playback/core/lib/recordandplayback/workers/*_worker.rb).
var bbbFailSteps = []struct{ dir, field string }{
	{"archived", "archive_failed"},
	{"sanity", "sanity_failed"},
	{"processed", "process_failed"},
	{"published", "publish_failed"},
}

// bbbRecordings counts the recordings whose processing failed, by step, and how long ago the newest
// failure was marked. It reads names and the mtime of the markers, never a file's content.
func bbbRecordings(ctx context.Context, _ Target) (map[string]any, error) {
	status := filepath.Join(bbbRecordingDir, "status")
	if info, err := os.Stat(status); err != nil || !info.IsDir() {
		if err == nil || errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: no BigBlueButton recording status on this host", ErrUnsupported)
		}
		return nil, errors.New("the BigBlueButton recording status cannot be read")
	}
	values := map[string]any{}
	failed := 0
	var newest time.Time
	for _, step := range bbbFailSteps {
		n, last, err := countFailMarkers(ctx, filepath.Join(status, step.dir), maxStatusEntries)
		if err != nil {
			return nil, fmt.Errorf("status/%s: %w", step.dir, err)
		}
		values[step.field] = n
		failed += n
		if last.After(newest) {
			newest = last
		}
	}
	values["failed"] = failed
	if failed > 0 {
		values["newest_fail_age_s"] = max(int(now().Sub(newest).Seconds()), 0)
	}
	return values, nil
}

// countFailMarkers counts the regular files *.fail in dir and returns the newest mtime among them; a
// step that never ran has no directory yet and no marker. A directory of more than limit entries is
// an error, not counted in part, and so is the end of ctx between two batches of entries.
func countFailMarkers(ctx context.Context, dir string, limit int) (int, time.Time, error) {
	f, err := os.Open(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return 0, time.Time{}, nil
	}
	if err != nil {
		return 0, time.Time{}, errors.New("cannot be read")
	}
	defer f.Close()
	n, seen := 0, 0
	var newest time.Time
	for {
		if err := ctx.Err(); err != nil {
			return 0, time.Time{}, err
		}
		entries, err := f.ReadDir(4096)
		seen += len(entries)
		if seen > limit {
			return 0, time.Time{}, fmt.Errorf("more than %d entries", limit)
		}
		for _, e := range entries {
			if !e.Type().IsRegular() || !strings.HasSuffix(e.Name(), ".fail") {
				continue
			}
			info, err := e.Info()
			if err != nil {
				continue // removed since it was listed
			}
			n++
			if info.ModTime().After(newest) {
				newest = info.ModTime()
			}
		}
		if errors.Is(err, io.EOF) {
			return n, newest, nil
		}
		if err != nil {
			return 0, time.Time{}, errors.New("cannot be read")
		}
	}
}

// bbbWebUnit is the unit of bbb-web. The meetings view sends the checksum, which opens getMeetings
// to whoever holds it, only to the port of this unit.
const bbbWebUnit = "bbb-web.service"

// bbbPropertyFiles are where bbb-web reads its properties, the administrator's overrides first, then
// the packaged defaults (bbb-conf, get_bbb_web_config_value); tests point them elsewhere.
var bbbPropertyFiles = []string{
	"/etc/bigbluebutton/bbb-web.properties",
	"/usr/share/bbb-web/WEB-INF/classes/bigbluebutton.properties",
}

// bbbEndpoint finds where the unit of bbb-web listens; tests point it at their server.
var bbbEndpoint = resolve

// maxPropertyBytes caps what the meetings view reads of one properties file; the packaged one has
// some 30 KiB.
const maxPropertyBytes = 1 << 20

// maxMeetingValueBytes caps the text of one element the meetings view keeps: a count, a flag, a
// returncode or a messageKey.
const maxMeetingValueBytes = 64

// bbbChecksums are the algorithms bbb-web may check an API checksum with, in the order the meetings
// view takes them: sha256 as the API documents it, else the strongest one bbb-web allows. bbb-web
// tells them apart by the length of the checksum (GetChecksumValidator).
var bbbChecksums = []struct {
	name string
	hash func() hash.Hash
}{
	{"sha256", sha256.New},
	{"sha512", sha512.New},
	{"sha384", sha512.New384},
	{"sha1", sha1.New},
}

// bbbMeetingCounts are the elements of a <meeting> the meetings view adds up, by field.
var bbbMeetingCounts = map[string]string{
	"participantCount":      "participants",
	"listenerCount":         "listeners",
	"voiceParticipantCount": "voice",
	"videoCount":            "video",
}

// bbbMeetingFlags are the elements of a <meeting> by whose value true the view counts the meeting, by
// field.
var bbbMeetingFlags = map[string]string{"running": "running", "recording": "recording"}

// bbbMeetingFields are the fields of the meetings view.
var bbbMeetingFields = []string{"meetings", "running", "participants", "listeners", "voice", "video", "recording"}

// messageKeyPattern is a messageKey of bbb-web that the view repeats in its error; any other text of
// the server it does not.
var messageKeyPattern = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]{0,63}$`)

// bbbMeetings counts the meetings on this BigBlueButton server and their participants through the
// call getMeetings of bbb-web's API on bbb-web's own port. The API's secret leaves this function only
// as the checksum in the URL; of the answer the view keeps the counts and flags of each meeting,
// never a name, a password, an attendee or metadata.
func bbbMeetings(ctx context.Context, t Target) (map[string]any, error) {
	if t.Name != bbbWebUnit {
		return nil, fmt.Errorf("%w: view bbb_meetings reads only the unit %s", ErrInvalid, bbbWebUnit)
	}
	checksum, err := bbbChecksum("getMeetings")
	if err != nil {
		return nil, err
	}
	ep, err := bbbEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	u := url.URL{
		Scheme:   "http",
		Host:     netip.AddrPortFrom(ep.addr, ep.port).String(),
		Path:     "/bigbluebutton/api/getMeetings",
		RawQuery: "checksum=" + checksum,
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, errors.New("the request to bbb-web cannot be built")
	}
	resp, err := NewGuard(ep.extra...).HTTPClient(nil).Do(req)
	if err != nil {
		// A url.Error quotes the URL, and with it the checksum.
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		if strings.Contains(err.Error(), checksum) {
			err = errors.New("bbb-web cannot be asked")
		}
		return nil, netErr(ctx, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bbb-web answers getMeetings with HTTP %d", resp.StatusCode)
	}
	values, err := countMeetings(resp.Body)
	if err != nil {
		return nil, netErr(ctx, err)
	}
	return values, nil
}

// bbbChecksum returns the checksum bbb-web expects of call without parameters: the hex hash of call
// and the secret, in an algorithm bbb-web allows (GetChecksumValidator). Without a secret on this
// host the view is unsupported.
func bbbChecksum(call string) (string, error) {
	props, err := bbbProperties("securitySalt", "supportedChecksumAlgorithms")
	if err != nil {
		return "", err
	}
	salt := props["securitySalt"]
	if salt == "" {
		return "", fmt.Errorf("%w: no BigBlueButton API secret on this host", ErrUnsupported)
	}
	// bbb-web compares with String.contains, so the view does too.
	allowed, ok := props["supportedChecksumAlgorithms"]
	if !ok {
		allowed = "sha256" // the default of the packaged properties allows it
	}
	for _, c := range bbbChecksums {
		if strings.Contains(allowed, c.name) {
			h := c.hash()
			h.Write([]byte(call + salt))
			return hex.EncodeToString(h.Sum(nil)), nil
		}
	}
	return "", errors.New("bbb-web allows no checksum algorithm the agent knows")
}

// bbbProperties returns the first value that is not empty of each key in bbbPropertyFiles, as bbb-conf
// reads them; it keeps no other line of the files.
func bbbProperties(keys ...string) (map[string]string, error) {
	found := map[string]string{}
	for _, name := range bbbPropertyFiles {
		b, err := readCapped(name, maxPropertyBytes)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("the BigBlueButton configuration %w", err)
		}
		for line := range strings.Lines(string(b)) {
			key, value, ok := strings.Cut(strings.TrimLeft(line, " \t\f"), "=")
			key = strings.TrimRight(key, " \t\f")
			if !ok || !slices.Contains(keys, key) {
				continue
			}
			value = strings.TrimRight(strings.TrimLeft(value, " \t\f"), "\r\n")
			if _, seen := found[key]; !seen && value != "" {
				found[key] = value
			}
		}
	}
	return found, nil
}

// readCapped reads the file name, which must not be larger than limit bytes. Its errors name neither
// the file nor its content but wrap fs.ErrNotExist.
func readCapped(name string, limit int64) ([]byte, error) {
	f, err := os.Open(name)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, fs.ErrNotExist
	}
	if err != nil {
		return nil, errors.New("cannot be read")
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, errors.New("cannot be read")
	}
	if int64(len(b)) > limit {
		return nil, fmt.Errorf("is larger than %d bytes", limit)
	}
	return b, nil
}

// countMeetings reads the answer of getMeetings token by token. It keeps the returncode and messageKey
// of the response and the counts and flags of each meeting; any other text it passes over.
func countMeetings(r io.Reader) (map[string]any, error) {
	counts := map[string]int{}
	var path []string
	var text []byte
	var code, key, errorKey string
	rooted := false
	dec := xml.NewDecoder(r)
	for {
		tok, err := dec.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, xmlError(err)
		}
		switch tok := tok.(type) {
		case xml.StartElement:
			path = append(path, tok.Name.Local)
			text = text[:0]
			if len(path) == 1 && path[0] != "response" {
				return nil, errors.New("the answer of bbb-web is no API response")
			}
			rooted = true
			if meetingPath(path) {
				counts["meetings"]++
			}
		case xml.CharData:
			if keptPath(path) {
				if len(text)+len(tok) > maxMeetingValueBytes {
					return nil, fmt.Errorf("the answer of bbb-web has a <%s> longer than %d bytes", path[len(path)-1], maxMeetingValueBytes)
				}
				text = append(text, tok...)
			}
		case xml.EndElement:
			if keptPath(path) {
				name, value := path[len(path)-1], strings.TrimSpace(string(text))
				switch {
				case len(path) == 2 && name == "returncode":
					code = value
				case len(path) == 2 && name == "messageKey":
					key = value
				case path[1] == "errors":
					if errorKey == "" {
						errorKey = value
					}
				case bbbMeetingFlags[name] != "":
					if value == "true" {
						counts[bbbMeetingFlags[name]]++
					}
				default:
					n, err := strconv.Atoi(value)
					if err != nil || n < 0 {
						return nil, fmt.Errorf("the answer of bbb-web has a <%s> that is no count", name)
					}
					counts[bbbMeetingCounts[name]] += n
				}
			}
			path = path[:len(path)-1]
		}
	}
	if !rooted { // text alone: the decoder takes it without a root element
		return nil, errNotXML
	}
	if key == "" {
		key = errorKey
	}
	switch {
	case code == "SUCCESS":
	case code == "FAILED" && key == "noMeetings":
		counts = map[string]int{}
	case code == "FAILED" && messageKeyPattern.MatchString(key):
		return nil, fmt.Errorf("bbb-web refuses getMeetings: %s", key)
	case code == "FAILED":
		return nil, errors.New("bbb-web refuses getMeetings without a messageKey the agent repeats")
	default:
		return nil, errors.New("the answer of bbb-web has no returncode")
	}
	values := make(map[string]any, len(bbbMeetingFields))
	for _, f := range bbbMeetingFields {
		values[f] = counts[f]
	}
	return values, nil
}

// meetingPath says whether path is a meeting of the answer: response/meetings/meeting.
func meetingPath(path []string) bool {
	return len(path) == 3 && path[0] == "response" && path[1] == "meetings" && path[2] == "meeting"
}

// keptPath says whether the text of the element at path is one the meetings view keeps: returncode
// and messageKey of the response, the key of its first error and a count or flag of a meeting. A
// metadata or attendee element of the same name lies deeper and is not one.
func keptPath(path []string) bool {
	switch len(path) {
	case 2:
		return path[1] == "returncode" || path[1] == "messageKey"
	case 4:
		if path[1] == "errors" {
			return path[2] == "error" && path[3] == "key"
		}
		name := path[3]
		return meetingPath(path[:3]) && (bbbMeetingCounts[name] != "" || bbbMeetingFlags[name] != "")
	}
	return false
}

// errNotXML is an answer of bbb-web that is no XML document; it quotes nothing of the answer.
var errNotXML = errors.New("the answer of bbb-web is no well-formed XML")

// xmlError is the view's error for err, met reading the answer: the cap of the body, or a fixed text
// that quotes nothing of the answer.
func xmlError(err error) error {
	if errors.Is(err, errBodyTooLarge) {
		return errBodyTooLarge
	}
	var se *xml.SyntaxError
	if errors.As(err, &se) {
		return errNotXML
	}
	return errors.New("the answer of bbb-web cannot be read")
}
