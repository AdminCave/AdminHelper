#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hermetic test of .github/scripts/cache_settings.sh: needs bash, awk and sed only. Runs in the
# CI job ops-scripts, like tauri_cli_pins_test.sh.
# Last, the real workflows must pass it: that is the guard on ci.yml, release.yml (--uncached) and
# docker.yml (--tag-uncached).

set -uo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
tool="$root/.github/scripts/cache_settings.sh"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

passed=0 failed=0
check() { # check <name> <expected> <actual>
    if [ "$2" = "$3" ]; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        echo "FAIL $1: expected '$2', got '$3'" >&2
    fi
}
run() { # run <file…> → "<rc>"
    local rc=0
    bash "$tool" "$@" >"$work/out" 2>&1 || rc=$?
    echo "$rc"
}

cat >"$work/good.yml" <<'YML'
jobs:
  rust:
    steps:
      - uses: actions/checkout@v7
      # A comment between steps: cache-bin: true
      - uses: Swatinem/rust-cache@d1527c8f67ef9af357290475d4af4b0fab8f12e0 # v2.9.3
        with:
          workspaces: apps/desktop/src-tauri
          cache-bin: false
      - uses: Swatinem/rust-cache@v2
        with:
          cache-bin: "false" # quoted
      - uses: actions/cache@v6
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('apps/web/package-lock.json') }}-chromium
      - uses: actions/cache@v6
        with:
          path: ~/apt-archives
          key: apt-${{ steps.week.outputs.week }}
          restore-keys: apt-
YML
check "settings in place: green" 0 "$(run "$work/good.yml")"
check "green names the file count" "cache_settings: ok (1)" "$(cat "$work/out")"

sed '9d' "$work/good.yml" >"$work/nobin.yml"
check "rust-cache without cache-bin: red" 1 "$(run "$work/nobin.yml")"
check "red names file and line" "::error file=$work/nobin.yml,line=6::rust-cache step without cache-bin: false" "$(cat "$work/out")"

sed 's/^\(          cache-bin: \)false$/\1true/' "$work/good.yml" >"$work/bintrue.yml"
check "cache-bin: true: red" 1 "$(run "$work/bintrue.yml")"

sed 's/^          cache-bin: false$/          # cache-bin: false/' "$work/good.yml" >"$work/bincomment.yml"
check "cache-bin only in a comment: red" 1 "$(run "$work/bincomment.yml")"

# cache-bin of the NEXT step must not cover a rust-cache step without it.
cat >"$work/next.yml" <<'YML'
    steps:
      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: apps/desktop/src-tauri
      - name: other
        with:
          cache-bin: false
YML
check "cache-bin in the next step does not count: red" 1 "$(run "$work/next.yml")"

# Nor a key at the job level after the last step.
cat >"$work/joblevel.yml" <<'YML'
jobs:
  rust:
    steps:
      - uses: Swatinem/rust-cache@v2
  other:
    cache-bin: false
YML
check "cache-bin after the step block does not count: red" 1 "$(run "$work/joblevel.yml")"

sed "s/\${{ hashFiles('apps\/web\/package-lock.json') }}/\${{ steps.playwright.outputs.version }}/" \
    "$work/good.yml" >"$work/pwversion.yml"
check "playwright key without hashFiles: red" 1 "$(run "$work/pwversion.yml")"
check "red names the playwright step" "::error file=$work/pwversion.yml,line=13::ms-playwright cache whose key does not use hashFiles(" "$(cat "$work/out")"

sed '16a\          restore-keys: playwright-' "$work/good.yml" >"$work/pwrestore.yml"
check "playwright cache with restore-keys: red" 1 "$(run "$work/pwrestore.yml")"

# R-1309: a quoted uses: is the same action, and owner/repo match case-insensitively.
for q in "'" '"'; do
    printf '    steps:\n      - uses: %sSwatinem/Rust-Cache@v2%s\n        with:\n          workspaces: x\n' \
        "$q" "$q" >"$work/quoted.yml"
    check "quoted ($q) rust-cache without cache-bin: red" 1 "$(run "$work/quoted.yml")"
done

# cache-bin counts only in the with: block of the step, not under env:.
cat >"$work/binenv.yml" <<'YML'
    steps:
      - uses: Swatinem/rust-cache@v2
        env:
          cache-bin: false
        with:
          workspaces: x
YML
check "cache-bin under env: red" 1 "$(run "$work/binenv.yml")"

cat >"$work/bindir.yml" <<'YML'
    steps:
      - uses: Swatinem/rust-cache@v2
        with:
          cache-bin: false
          cache-directories: |
            target/extra
            ~/.cargo/bin
YML
check "rust-cache cache-directories on .cargo/bin: red" 1 "$(run "$work/bindir.yml")"
check "red names the cache-directories step" "::error file=$work/bindir.yml,line=2::rust-cache cache-directories names .cargo/bin" "$(cat "$work/out")"

cat >"$work/cachebin.yml" <<'YML'
    steps:
      - uses: "actions/cache/restore@v6"
        with:
          key: tools
          path:
            - ~/.cargo/registry
            - ~/.cargo/bin
      - run: true
YML
check "actions/cache path list on .cargo/bin: red" 1 "$(run "$work/cachebin.yml")"
check "red names the actions/cache step" "::error file=$work/cachebin.yml,line=2::actions/cache path names .cargo/bin" "$(cat "$work/out")"

sed 's|~/.cargo/bin|~/.cargo/git|' "$work/cachebin.yml" >"$work/cachegit.yml"
check "actions/cache path list without .cargo/bin: green" 0 "$(run "$work/cachegit.yml")"

# .cargo/bin outside path/cache-directories (a run: line) is no cache setting.
cat >"$work/binrun.yml" <<'YML'
    steps:
      - uses: actions/cache@v6
        with:
          path: ~/.cargo/registry
          key: k
      - run: ls ~/.cargo/bin
YML
check ".cargo/bin in a run step: green" 0 "$(run "$work/binrun.yml")"

# R-1288: a workflow given with --uncached restores no cache at all.
cat >"$work/uncached.yml" <<'YML'
    steps:
      - uses: actions/setup-node@v7
        with:
          node-version: "26"
          package-manager-cache: false
      - uses: actions/setup-go@v7
        with:
          go-version: "1.27"
          cache: false
      - uses: actions/setup-python@v6
        with:
          python-version: "3.14"
YML
check "uncached settings in place: green" 0 "$(run --uncached "$work/uncached.yml")"
check "good.yml uncached: red (rust-cache, actions/cache)" 1 "$(run --uncached "$work/good.yml")"
check "good.yml without --uncached stays green" 0 "$(run "$work/good.yml")"

sed '/package-manager-cache: false/d' "$work/uncached.yml" >"$work/u-pm.yml"
check "setup-node without package-manager-cache: false: red" 1 "$(run --uncached "$work/u-pm.yml")"
check "red names the setup-node step" "::error file=$work/u-pm.yml,line=2::setup-node without package-manager-cache: false or with cache:" "$(cat "$work/out")"

sed 's/package-manager-cache: false/package-manager-cache: false\n          cache: npm/' "$work/uncached.yml" >"$work/u-npm.yml"
check "setup-node with cache: npm: red" 1 "$(run --uncached "$work/u-npm.yml")"

sed '/          cache: false/d' "$work/uncached.yml" >"$work/u-go.yml"
check "setup-go without cache: false (default on): red" 1 "$(run --uncached "$work/u-go.yml")"
check "red names the setup-go step" "::error file=$work/u-go.yml,line=6::setup-go without cache: false" "$(cat "$work/out")"

sed 's/          cache: false/          cache: true/' "$work/uncached.yml" >"$work/u-gotrue.yml"
check "setup-go with cache: true: red" 1 "$(run --uncached "$work/u-gotrue.yml")"

sed 's/python-version: "3.14"/python-version: "3.14"\n          cache: pip/' "$work/uncached.yml" >"$work/u-py.yml"
check "setup-python with cache: pip: red" 1 "$(run --uncached "$work/u-py.yml")"

printf '    steps:\n      - uses: actions/cache/restore@v6\n        with:\n          path: x\n          key: k\n' >"$work/u-restore.yml"
check "actions/cache/restore in an uncached workflow: red" 1 "$(run --uncached "$work/u-restore.yml")"
check "red names the cache step" "::error file=$work/u-restore.yml,line=2::cache step in a workflow that runs without caches" "$(cat "$work/out")"

# R-1350: more cache sources under --uncached, each green once switched off.
cat >"$work/u-more.yml" <<'YML'
    steps:
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: false
      - uses: ruby/setup-ruby@v1
        with:
          ruby-version: "3.4"
          bundler-cache: false
      - uses: actions/setup-dotnet@v5
        with:
          dotnet-version: "10.0"
          cache: false
      - uses: docker/build-push-action@v7
        with:
          context: .
          no-cache: true
YML
check "more sources switched off: green" 0 "$(run --uncached "$work/u-more.yml")"

sed '/enable-cache: false/d' "$work/u-more.yml" >"$work/u-uv.yml"
check "setup-uv without enable-cache: false (default auto): red" 1 "$(run --uncached "$work/u-uv.yml")"
check "red names the setup-uv step" "::error file=$work/u-uv.yml,line=2::setup-uv without enable-cache: false" "$(cat "$work/out")"

sed 's/bundler-cache: false/bundler-cache: true/' "$work/u-more.yml" >"$work/u-ruby.yml"
check "setup-ruby with bundler-cache: true: red" 1 "$(run --uncached "$work/u-ruby.yml")"

sed 's/          cache: false/          cache: true/' "$work/u-more.yml" >"$work/u-dotnet.yml"
check "setup-dotnet with cache: true: red" 1 "$(run --uncached "$work/u-dotnet.yml")"

sed 's/          no-cache: true/          cache-from: type=gha,scope=server/' "$work/u-more.yml" >"$work/u-gha.yml"
check "build-push-action with cache-from type=gha: red" 1 "$(run --uncached "$work/u-gha.yml")"
check "red names the build step" "::error file=$work/u-gha.yml,line=13::build-push-action with cache-from/cache-to or without no-cache: true" "$(cat "$work/out")"

sed 's/          no-cache: true/          no-cache: true\n          cache-to: type=gha,mode=max/' "$work/u-more.yml" >"$work/u-ghato.yml"
check "build-push-action with no-cache and cache-to: red" 1 "$(run --uncached "$work/u-ghato.yml")"

sed '/no-cache: true/d' "$work/u-more.yml" >"$work/u-bpa.yml"
check "build-push-action without no-cache: red" 1 "$(run --uncached "$work/u-bpa.yml")"

# R-1349: --tag-uncached keeps the build cache on main and switches it off on tags.
cat >"$work/t-good.yml" <<'YML'
    steps:
      - uses: docker/build-push-action@v7
        with:
          context: .
          no-cache: ${{ startsWith(github.ref, 'refs/tags/') }}
          cache-from: ${{ !startsWith(github.ref, 'refs/tags/') && format('type=gha,scope={0}', matrix.image) || '' }}
          cache-to: ${{ !startsWith(github.ref, 'refs/tags/') && format('type=gha,mode=max,scope={0}', matrix.image) || '' }}
YML
check "tag-guarded build cache: green" 0 "$(run --tag-uncached "$work/t-good.yml")"
check "tag-guarded build cache under --uncached: red" 1 "$(run --uncached "$work/t-good.yml")"

sed '/no-cache:/d' "$work/t-good.yml" >"$work/t-nonc.yml"
check "tag-uncached without no-cache: red" 1 "$(run --tag-uncached "$work/t-nonc.yml")"
check "red names the tag build step" "::error file=$work/t-nonc.yml,line=2::build-push-action not switched off on tags (no-cache/cache-from/cache-to)" "$(cat "$work/out")"

sed 's/no-cache: .*/no-cache: true/' "$work/t-good.yml" >"$work/t-nctrue.yml"
check "tag-uncached with no-cache: true but guarded cache: red" 1 "$(run --tag-uncached "$work/t-nctrue.yml")"

sed 's/cache-from: .*/cache-from: type=gha,scope=server/' "$work/t-good.yml" >"$work/t-from.yml"
check "tag-uncached with unguarded cache-from: red" 1 "$(run --tag-uncached "$work/t-from.yml")"

sed 's/cache-to: .*/cache-to: type=gha,mode=max/' "$work/t-good.yml" >"$work/t-to.yml"
check "tag-uncached with unguarded cache-to: red" 1 "$(run --tag-uncached "$work/t-to.yml")"

sed 's/startsWith(github.ref, .refs\/tags\/.) }}/startsWith(github.ref, '"'"'refs\/heads\/'"'"') }}/' "$work/t-good.yml" >"$work/t-heads.yml"
check "tag-uncached with no-cache on heads: red" 1 "$(run --tag-uncached "$work/t-heads.yml")"

sed 's/no-cache:/# no-cache:/' "$work/t-good.yml" >"$work/t-com.yml"
check "tag-uncached with no-cache commented out: red" 1 "$(run --tag-uncached "$work/t-com.yml")"

cat "$work/t-good.yml" - >"$work/t-rust.yml" <<'YML'
      - uses: Swatinem/rust-cache@v2
        with:
          cache-bin: false
YML
check "tag-uncached with another cache step: red" 1 "$(run --tag-uncached "$work/t-rust.yml")"

# A with: written as a flow mapping is not read: red in every mode.
printf '    steps:\n      - uses: actions/cache@v6\n        with: { path: ~/.cargo/bin, key: k }\n' >"$work/flow.yml"
check "with: as a flow mapping: red" 1 "$(run "$work/flow.yml")"
check "red names the flow mapping" "::error file=$work/flow.yml,line=2::with: as a flow mapping is not checked, write it as a block" "$(cat "$work/out")"
printf '    steps:\n      - uses: actions/setup-python@v6\n        with: {python-version: "3.14", cache: pip}\n' >"$work/u-flow.yml"
check "setup-python cache in a flow mapping (uncached): red" 1 "$(run --uncached "$work/u-flow.yml")"

# Step keys may start further than one space after the dash.
printf '    steps:\n      -   uses: Swatinem/rust-cache@v2\n          with:\n            workspaces: x\n' >"$work/wide.yml"
check "rust-cache after a wide dash without cache-bin: red" 1 "$(run "$work/wide.yml")"
printf '    steps:\n      -   uses: Swatinem/rust-cache@v2\n          with:\n            cache-bin: false\n            cache-directories: ~/.cargo/bin\n' >"$work/widedir.yml"
check "wide dash, cache-directories on .cargo/bin: red" 1 "$(run "$work/widedir.yml")"
printf '    steps:\n      -   uses: Swatinem/rust-cache@v2\n          with:\n            cache-bin: false\n' >"$work/widegood.yml"
check "wide dash with cache-bin: false: green" 0 "$(run "$work/widegood.yml")"

# A list at the height of its key belongs to that key.
printf '    steps:\n      - uses: actions/cache@v6\n        with:\n          path:\n          - ~/.cargo/bin\n          key: k\n' >"$work/flatlist.yml"
check "path list at key height on .cargo/bin: red" 1 "$(run "$work/flatlist.yml")"
check "red names the flat-list step" "::error file=$work/flatlist.yml,line=2::actions/cache path names .cargo/bin" "$(cat "$work/out")"
printf '    steps:\n      - uses: actions/checkout@v7\n      - uses: Swatinem/rust-cache@v2\n        with:\n          cache-bin: false\n' >"$work/afterlist.yml"
check "steps after each other stay apart: green" 0 "$(run "$work/afterlist.yml")"

# R-1354: a tag-guarded cache must give the tag the empty value, nothing else.
sed "s/ || '' }}\$/ || 'type=gha' }}/" "$work/t-good.yml" >"$work/t-else.yml"
check "tag-uncached cache-from with a value of its own on tags: red" 1 "$(run --tag-uncached "$work/t-else.yml")"
sed "s/ && format(/ \&\& 'x' || format(/" "$work/t-good.yml" >"$work/t-mid.yml"
check "tag-uncached cache-from with a further || in the middle: red" 1 "$(run --tag-uncached "$work/t-mid.yml")"

# R-1354: docker/bake-action and docker build in run: are not read, so a workflow without caches refuses them.
printf '    steps:\n      - uses: docker/bake-action@v6\n        with:\n          no-cache: true\n' >"$work/bake.yml"
check "bake-action (uncached): red" 1 "$(run --uncached "$work/bake.yml")"
check "red names the bake step" "::error file=$work/bake.yml,line=2::docker/bake-action is not checked, build with build-push-action" "$(cat "$work/out")"
check "bake-action (tag-uncached): red" 1 "$(run --tag-uncached "$work/bake.yml")"
check "bake-action in a cached workflow: green" 0 "$(run "$work/bake.yml")"
printf '    steps:\n      - name: build\n        run: docker buildx build --no-cache .\n' >"$work/runb.yml"
check "docker buildx build in run: (tag-uncached): red" 1 "$(run --tag-uncached "$work/runb.yml")"
check "red names the run step" "::error file=$work/runb.yml,line=2::docker build/bake in a run: step is not checked, build with build-push-action" "$(cat "$work/out")"
check "docker buildx build in run: in a cached workflow: green" 0 "$(run "$work/runb.yml")"
printf '    steps:\n      - run: |\n          set -e\n          docker build -t x .\n' >"$work/runblk.yml"
check "docker build in a run: block (uncached): red" 1 "$(run --uncached "$work/runblk.yml")"
printf '    steps:\n      - run: |\n          docker buildx bake all\n' >"$work/runbake.yml"
check "docker buildx bake in a run: block (uncached): red" 1 "$(run --uncached "$work/runbake.yml")"
printf '    steps:\n      - run: |\n          docker buildx imagetools inspect x\n          echo docker-build\n' >"$work/runok.yml"
check "imagetools and a mere mention in run: (uncached): green" 0 "$(run --uncached "$work/runok.yml")"

# R-1355: a flow mapping on the line below with: is a flow mapping too.
printf '    steps:\n      - uses: Swatinem/rust-cache@v2\n        with:\n          {cache-bin: false}\n' >"$work/flownext.yml"
check "flow mapping on the line below with:: red" 1 "$(run "$work/flownext.yml")"
check "red names the next-line flow mapping" "::error file=$work/flownext.yml,line=2::with: as a flow mapping is not checked, write it as a block" \
    "$(grep -F 'flow mapping' "$work/out")"

# R-1355: a step named first, uses: one line below.
printf '    steps:\n      - name: rust cache\n        uses: Swatinem/rust-cache@v2\n        with:\n          workspaces: x\n' >"$work/named.yml"
check "named rust-cache step without cache-bin: red" 1 "$(run "$work/named.yml")"
check "red names the named step" "::error file=$work/named.yml,line=2::rust-cache step without cache-bin: false" "$(cat "$work/out")"
printf '    steps:\n      - name: rust cache\n        uses: Swatinem/rust-cache@v2\n        with:\n          cache-bin: false\n' >"$work/namedgood.yml"
check "named rust-cache step with cache-bin: false: green" 0 "$(run "$work/namedgood.yml")"

check "--uncached without a file: usage" 2 "$(run --uncached)"
check "--tag-uncached without a file: usage" 2 "$(run --tag-uncached)"
check "unknown option: usage" 2 "$(run --cached "$work/good.yml")"

check "one bad file among good ones: red" 1 "$(run "$work/good.yml" "$work/nobin.yml")"
check "no argument: usage" 2 "$(run)"
check "unreadable file: usage" 2 "$(run "$work/missing.yml")"

check "real ci.yml, release.yml (uncached), docker.yml (tag-uncached): green" 0 \
    "$(run "$root/.github/workflows/ci.yml" --uncached "$root/.github/workflows/release.yml" \
        --tag-uncached "$root/.github/workflows/docker.yml")"
[ "$(grep -c . "$work/out")" = 1 ] || cat "$work/out" >&2

echo "cache_settings_test: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
