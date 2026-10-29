// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"html"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// The documentation tells an admin which agent commands to type, and no other test
// reads them: `run --verbose`, `monitor run --dry-run` and `frpc rotate` stood in the
// troubleshooting pages without existing (R-0731). These tests read every <code> of
// docs/**/*.html and check each call against the real command tree, with the parser
// and the helper process of the box scripts (box_cli_test.go).

// docsCallFloor is a non-empty guard, not a quota: a reader that quietly loses most
// of the calls has to fail too, so it sits just below the real number (28 today).
// Lower it only after confirming the documentation, not the reader, is what changed.
const docsCallFloor = 27

var (
	// codeRE is a <code> element, with attributes too, as in scripts/dev/doc-smoke.py.
	codeRE = regexp.MustCompile(`(?s)<code\b[^>]*>(.*?)</code>`)
	tagRE  = regexp.MustCompile(`<[^>]+>`)
	// commentRE is a shell comment: a # at the start of the line or after a blank.
	commentRE = regexp.MustCompile(`(^|\s)#.*$`)
	// docCallRE is the name as a word of its own, followed by a subcommand or a flag:
	// not `apt install adminhelper-agent`, adminhelper-agent.timer or the bare name.
	docCallRE = regexp.MustCompile(`(^|[\s"'(;|&{!])adminhelper-agent[ \t]+[a-z-]`)
	// pathCallRE is a call through a path (./, .\, /usr/bin/) or as the Windows binary
	// (adminhelper-agent-windows-x86_64.exe), with a subcommand or flag after it. It is
	// read as the bare name; `apt install ./adminhelper-agent_1_amd64.deb` and the
	// build path ./cmd/adminhelper-agent are no calls.
	pathCallRE = regexp.MustCompile(`(^|[\s"'(;|&{!])(?:\.{0,2}[\\/]|(?:[A-Za-z]:)?[\\/](?:[\w.-]+[\\/])*)?adminhelper-agent(?:-windows-x86_64)?(?:\.exe)?([ \t]+[a-z-])`)
	// quotedExeRE is the PowerShell call of an installed binary with a path that holds
	// blanks: & 'C:\Program Files\AdminHelper\adminhelper-agent.exe' provision
	quotedExeRE = regexp.MustCompile(`(?:^[ \t]*&[ \t]*)?['"][^'"]*[\\/]adminhelper-agent(?:-windows-x86_64)?(?:\.exe)?['"]([ \t]+[a-z-])`)
	// psContinuedRE is a PowerShell line continuation, a backtick at the end of the line.
	psContinuedRE = regexp.MustCompile("`[ \t]*$")
	// placeholderRE is a value the reader fills in, <provision-token>. parseCalls takes
	// its < for a redirect and would end the call there, before the flags after it.
	placeholderRE = regexp.MustCompile(`<[A-Za-z0-9_.-]+>`)
)

// docCalls reads the agent calls out of the <code> elements of one page. Only the
// lines whose (continued) command names a subcommand or a flag go to parseCalls; the
// others stay empty, and empty lines in front of each body keep the page's line
// numbers in what parseCalls reports.
func docCalls(name, page string) (calls []agentCall, unknown []string) {
	for _, m := range codeRE.FindAllStringSubmatchIndex(page, -1) {
		body := html.UnescapeString(tagRE.ReplaceAllString(page[m[2]:m[3]], ""))
		// VALUE is no subcommand to parseCalls: wordRE takes lower case only.
		body = placeholderRE.ReplaceAllString(body, "VALUE")
		lines := strings.Split(strings.ReplaceAll(body, "\r\n", "\n"), "\n")
		for i, l := range lines {
			l = psContinuedRE.ReplaceAllString(commentRE.ReplaceAllString(l, ""), " \\")
			l = quotedExeRE.ReplaceAllString(l, "adminhelper-agent${1}")
			lines[i] = pathCallRE.ReplaceAllString(l, "${1}adminhelper-agent${2}")
		}
		joined, numbers := logicalLines(lines)
		keep, kept := make([]string, len(lines)), false
		for i, l := range joined {
			if !docCallRE.MatchString(l) {
				continue
			}
			end := len(lines)
			if i+1 < len(numbers) {
				end = numbers[i+1] - 1
			}
			copy(keep[numbers[i]-1:end], lines[numbers[i]-1:end])
			kept = true
		}
		if !kept {
			continue
		}
		before := make([]string, strings.Count(page[:m[2]], "\n"))
		c, u := parseCalls(name, append(before, keep...))
		calls, unknown = append(calls, c...), append(unknown, u...)
	}
	return calls, unknown
}

func TestDocsCallTheAgentCLIAsItIs(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "docs")
	var pages []string
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() && strings.HasSuffix(p, ".html") {
			pages = append(pages, p)
		}
		return err
	})
	if err != nil || len(pages) == 0 {
		t.Fatalf("no pages under %s (%v)", dir, err)
	}
	found := 0
	for _, p := range pages {
		data, err := os.ReadFile(p)
		if err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		calls, unknown := docCalls("docs/"+filepath.ToSlash(rel), string(data))
		for _, u := range unknown {
			t.Error(u)
		}
		for _, c := range calls {
			found++
			if err := checkCall(c); err != nil {
				t.Errorf("%s: %v", c.where, err)
			}
		}
	}
	if found < docsCallFloor {
		t.Errorf("%d adminhelper-agent calls found in the docs, want at least %d: the reader lost them, or the docs changed", found, docsCallFloor)
	}
}

func TestDocsCLICheckCanFail(t *testing.T) {
	const page = `<h2>Fixture</h2>
<pre><code>sudo adminhelper-agent run --verbose   # x</code></pre>
<pre><code>adminhelper-agent monitor run --dry-run
adminhelper-agent frpc rotate</code></pre>
<pre><code>sudo adminhelper-agent run --once --log-level debug
sudo adminhelper-agent provision \
    --url https://srm.example.com \
    --token &lt;provision-token&gt;
cd a &amp;&amp; sudo adminhelper-agent diagnostics
sudo apt install adminhelper-agent     # later
adminhelper-agent version   # prints the version
sudo adminhelper-agent provision --token &lt;t&gt; --server-idd x</code></pre>
<pre><code>.\adminhelper-agent-windows-x86_64.exe service install
/usr/bin/adminhelper-agent run --verbose
./adminhelper-agent run --once
adminhelper-agent-windows-x86_64.exe frpc rotate
sudo apt install ./adminhelper-agent_1_amd64.deb
cd apps/agent &amp;&amp; go run ./cmd/adminhelper-agent version
&amp; 'C:\Program Files\AdminHelper\adminhelper-agent.exe' provision ` + "`" + `
    --token-stdin ` + "`" + `
    --server-idd x
adminhelper-agent.exe version</code></pre>`
	// Where a call is, and whether its check passes. Line 10, apt install, is none, and neither is the .deb on line 17.
	want := map[string]bool{
		"fixture.html:2":  false, // run has no --verbose
		"fixture.html:3":  false, // monitor has no run
		"fixture.html:4":  false, // frpc has no rotate
		"fixture.html:5":  true,
		"fixture.html:6":  true,
		"fixture.html:9":  true,
		"fixture.html:11": true,  // the words of the comment are no subcommands
		"fixture.html:12": false, // the flag after the placeholder is checked too
		"fixture.html:13": true,  // the .exe through a path
		"fixture.html:14": false, // through /usr/bin, run has no --verbose
		"fixture.html:15": true,
		"fixture.html:16": false, // the .exe, frpc has no rotate
		"fixture.html:19": false, // PowerShell, quoted path, the flag after the backticks is checked
		"fixture.html:22": true,  // adminhelper-agent.exe
	}
	calls, unknown := docCalls("fixture.html", page)
	for _, u := range unknown {
		t.Error(u)
	}
	if len(calls) != len(want) {
		t.Fatalf("%d calls parsed, want %d: %v", len(calls), len(want), calls)
	}
	for _, c := range calls {
		ok, isCall := want[c.where]
		if !isCall {
			t.Errorf("%s: no call there, parsed %v", c.where, c)
			continue
		}
		if err := checkCall(c); (err == nil) != ok {
			t.Errorf("%s %v: check ok=%v, want ok=%v (%v)", c.where, c.words, err == nil, ok, err)
		}
	}
	// The continued lines of provision belong to its call.
	for _, c := range calls {
		if c.where == "fixture.html:6" && strings.Join(c.flags, " ") != "--url --token" {
			t.Errorf("provision: flags %v, want --url --token", c.flags)
		}
	}
}
