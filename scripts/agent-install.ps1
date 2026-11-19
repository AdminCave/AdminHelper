# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent-install.ps1 - one-command AdminHelper agent rollout for Windows, against a
# running AdminHelper server. In a PowerShell run as Administrator:
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.ps1))) `
#       -Server https://srm.example.com -ServerId <id> -CaFp <sha256>
#
# Without -Token the script asks for the provisioning token, hidden, so it stays out
# of the one-liner and the history. Unattended rollouts pass -Token instead.
#
# Trust model (Kevin 2026-11-19): the release files come from GitHub over HTTPS, and
# both are checked against the release's SHA256SUMS before anything changes. Windows
# has no minisign, so unlike agent-install.sh --from-github the signature of
# SHA256SUMS is NOT checked: authenticity rests on TLS to github.com. The agent then
# starts only the frpc.exe whose SHA-256 it pins itself.
#
# Parameters:
#   -Server URL     AdminHelper server URL (https); required with -ServerId
#   -ServerId ID    server entry ID (desktop provisioning tab); without it the script
#                   only installs or updates the agent service
#   -CaFp FP        SHA-256 fingerprint of the internal CA (desktop tab): verifies the
#                   first contact in the TLS handshake instead of trust-on-first-use
#   -Token T        one-time provision token (else asked for, hidden)
#   -Version X.Y.Z  release to install (default: the latest release)
#
# Run through a scriptblock, `exit` would close the caller's PowerShell, so every
# failure is a terminating error (throw), never exit.

param(
    [string]$Server = "",
    [string]$ServerId = "",
    [string]$CaFp = "",
    [string]$Token = "",
    [string]$Version = "",
    # Defines the functions and returns; for the tests only.
    [switch]$LoadOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the progress bar slows Invoke-WebRequest of PS 5.1 down tenfold

$Repo = "AdminCave/AdminHelper"
$AgentAsset = "adminhelper-agent-windows-x86_64.exe"
$FrpcAsset = "frpc-windows-x86_64.exe"

function Write-Log([string]$Message) { Write-Host "[agent-install] $Message" }
function Write-Warn([string]$Message) { Write-Warning "[agent-install] $Message" }

# Release sources: GitHub over https. AH_API_BASE / AH_DL_BASE point the CI test at a
# release it built itself; plain http is accepted only on the loopback address.
function Resolve-Base([string]$Value, [string]$Default) {
    if ([string]::IsNullOrEmpty($Value)) { return $Default }
    $uri = [Uri]$Value
    if ($uri.Scheme -eq "https") { return $Value.TrimEnd("/") }
    if ($uri.Scheme -eq "http" -and $uri.IsLoopback) { return $Value.TrimEnd("/") }
    throw "release base $Value must be https:// (plain http only on the loopback address)"
}

# The SHA-256 SHA256SUMS lists for one file name; throws if the name is missing or
# listed twice, so a file is never installed unchecked.
function Get-ExpectedHash([string[]]$SumsLines, [string]$Name) {
    $found = @()
    foreach ($line in $SumsLines) {
        if ($line -match '^([0-9a-fA-F]{64}) [ *](.+)$' -and $Matches[2].Trim() -eq $Name) {
            $found += $Matches[1].ToLowerInvariant()
        }
    }
    if ($found.Count -ne 1) { throw "SHA256SUMS lists $Name $($found.Count) times, expected once" }
    return $found[0]
}

function Assert-FileHash([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) {
        throw "SHA-256 of $(Split-Path -Leaf $Path) does not match SHA256SUMS ($actual != $Expected) - refusing the release"
    }
}

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Runs a native program and throws on a non-zero exit code (PowerShell 5.1 does not).
# $StdIn stays untyped: [string] would turn $null into "" and pipe an empty line.
function Invoke-Native([string]$Exe, [string[]]$Arguments, $StdIn = $null) {
    if ($null -ne $StdIn) { $StdIn | & $Exe @Arguments } else { & $Exe @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "$(Split-Path -Leaf $Exe) $($Arguments[0]) failed (exit $LASTEXITCODE)" }
}

if ($LoadOnly) { return }

if ($ServerId -and -not $Server) { throw "-ServerId requires -Server (https://...)" }
if ($Token -and -not $ServerId) { throw "-Token requires -ServerId" }
if ($Server -and -not $Server.StartsWith("https://")) { throw "-Server must be an https:// URL" }
if (-not (Test-Administrator)) { throw "run this in a PowerShell as Administrator - it installs a Windows service" }

# Windows PowerShell 5.1 on older Windows still offers TLS 1.0 first; GitHub needs 1.2.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$apiBase = Resolve-Base $env:AH_API_BASE "https://api.github.com"
$dlBase = Resolve-Base $env:AH_DL_BASE "https://github.com"

if ($Version) {
    # The version becomes part of the download URL: only X.Y.Z with an optional pre-release suffix.
    if ($Version.TrimStart("v") -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$') { throw "-Version must look like X.Y.Z, not $Version" }
    $tag = "v" + $Version.TrimStart("v")
} else {
    $tag = (Invoke-RestMethod -UseBasicParsing -Uri "$apiBase/repos/$Repo/releases/latest").tag_name
    if (-not $tag) { throw "could not read the latest release from $apiBase" }
}
Write-Log "release $tag"

$work = Join-Path ([IO.Path]::GetTempPath()) ("adminhelper-agent-install-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    foreach ($name in @("SHA256SUMS", $AgentAsset, $FrpcAsset)) {
        Invoke-WebRequest -UseBasicParsing -Uri "$dlBase/$Repo/releases/download/$tag/$name" -OutFile (Join-Path $work $name)
    }
    $sums = Get-Content -LiteralPath (Join-Path $work "SHA256SUMS")
    # Both files are checked before the first change on this host.
    foreach ($name in @($AgentAsset, $FrpcAsset)) {
        Assert-FileHash (Join-Path $work $name) (Get-ExpectedHash $sums $name)
    }
    Write-Log "SHA256SUMS matches the agent and frpc"

    # `service install` copies itself and the frpc-windows-x86_64.exe beside it into
    # the program folder, checks frpc against its pin, and installs or updates the service.
    Invoke-Native (Join-Path $work $AgentAsset) @("service", "install")
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $ServerId) {
    Write-Log "no -ServerId given - agent installed, skipping provisioning."
    return
}

# The agent installs into the 64-bit Program Files folder, also when this runs in a 32-bit PowerShell.
$programFiles = if ($env:ProgramW6432) { $env:ProgramW6432 } else { [Environment]::GetFolderPath("ProgramFiles") }
$agent = Join-Path $programFiles "AdminHelper Agent\adminhelper-agent.exe"
if (-not $Token) {
    $secure = Read-Host -AsSecureString "[agent-install] provision token (input hidden)"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if (-not $Token) { throw "no provision token given" }

$provArgs = @("provision", "--url", $Server, "--server-id", $ServerId, "--token-stdin")
if ($CaFp) {
    $provArgs += @("--ca-fp", $CaFp)
} else {
    # Without a fingerprint the first contact is trust-on-first-use, as in agent-install.sh:
    # the agent pins the certificate the server presents.
    $provArgs += "--insecure"
    Write-Warn "no -CaFp given - the agent pins the server certificate on first use;"
    # The desktop shows the CA fingerprint, which never equals the pinned server certificate.
    Write-Warn "compare the fingerprint the agent prints with the server certificate, as its notice says;"
    Write-Warn "or pass -CaFp (from the desktop's provisioning window) to verify the first contact."
}
# The token goes through stdin, never as a program argument visible in the process list.
Invoke-Native $agent $provArgs $Token
$Token = $null
Write-Log "agent installed and provisioned."
