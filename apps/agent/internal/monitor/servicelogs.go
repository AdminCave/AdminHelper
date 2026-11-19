// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// The error lines of a failed service leave the host only through cleanLogLine. It mirrors
// clean_log_line in apps/monitoring/app/service_inventory.py, which applies the same rules
// again on arrival; apps/monitoring/tests/service_log_redaction.json holds the vectors both
// sides pass. Lengths count characters (runes), as Python does.
const (
	maxLogLine   = 300
	maxAgentText = 500
	logRedacted  = "[REDACTED]"
)

// The value rules keep key, separator and quotes and replace only the value; the value is
// submatch 2. RE2 has no backreference and no lookaround, like the Python side expects.
const logValueQuoted = `"(?:[^"\\]|\\.)*(?:"|$)|'[^']*(?:'|$)`

var (
	logURLUserInfo = regexp.MustCompile(`\b([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/?#]+@`)
	logValueRules  = []*regexp.Regexp{
		regexp.MustCompile(`(?i)(authorization["']?\s*[:=]\s*)(` + logValueQuoted + `|.+)`),
		regexp.MustCompile(`(?i)((?:password|passwd|secret|token|key)[A-Za-z0-9_.-]{0,64}` +
			`["']?\s*[:=]\s*)(` + logValueQuoted + `|[^\s&]+)`),
	}
	logHexRun      = regexp.MustCompile(`\b[0-9A-Fa-f]{32,}\b`)
	logBase64Run   = regexp.MustCompile(`[A-Za-z0-9+/_-]{32,}={0,2}`)
	logTrailingRun = regexp.MustCompile(`\S*$`)
)

// logControlToSpace maps what cap_agent_text maps: C0, DEL, C1 and the line and paragraph
// separators, one for one, so a line can never start a forged line of its own.
func logControlToSpace(r rune) rune {
	if r < 0x20 || (r >= 0x7f && r < 0xa0) || r == 0x2028 || r == 0x2029 {
		return ' '
	}
	return r
}

func redactLogValue(text string, re *regexp.Regexp) string {
	var b strings.Builder
	last := 0
	for _, m := range re.FindAllStringSubmatchIndex(text, -1) {
		b.WriteString(text[last:m[0]])
		b.WriteString(text[m[2]:m[3]])
		value := text[m[4]:m[5]]
		quote := ""
		if value != "" && (value[0] == '"' || value[0] == '\'') {
			quote = value[:1]
		}
		b.WriteString(quote)
		b.WriteString(logRedacted)
		if quote != "" && len(value) > 1 && strings.HasSuffix(value, quote) {
			b.WriteString(quote)
		}
		last = m[1]
	}
	b.WriteString(text[last:])
	return b.String()
}

func redactBase64Run(run string) string {
	var digit, upper, lower bool
	for _, c := range run {
		digit = digit || unicode.IsDigit(c)
		upper = upper || unicode.IsUpper(c)
		lower = lower || unicode.IsLower(c)
	}
	if digit && upper && lower {
		return logRedacted
	}
	return run
}

// redactLog replaces every secret the rules find, in the order of redact() on the server.
func redactLog(text string) string {
	text = logURLUserInfo.ReplaceAllString(text, "${1}"+logRedacted+"@")
	for _, re := range logValueRules {
		text = redactLogValue(text, re)
	}
	text = logHexRun.ReplaceAllLiteralString(text, logRedacted)
	return logBase64Run.ReplaceAllStringFunc(text, redactBase64Run)
}

// cutRunes cuts s to at most n characters, the last one "…" when it cut.
func cutRunes(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[:n-1]) + "…"
}

// cleanLogLine is an error line as the agent sends it: on one line (control characters
// become spaces), redacted and cut to maxLogLine characters including the trailing "…".
// A line beyond maxAgentText is cut before the rules run and loses the token the cut split,
// since a rule may no longer recognize its rest; the final cut runs after the rules.
func cleanLogLine(line string) string {
	line = strings.ToValidUTF8(line, "�")
	text := strings.Map(logControlToSpace, cutRunes(line, maxAgentText))
	if utf8.RuneCountInString(line) > maxAgentText {
		text = logTrailingRun.ReplaceAllLiteralString(text, "")
	}
	return cutRunes(redactLog(text), maxLogLine)
}
