#!/usr/local/bin/php
<?php

/*
 * SPDX-FileCopyrightText: 2026 Kevin Stenzel
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

/*
 * The state of the AdminHelper agent for the settings page, as JSON. The agent's files hold its
 * keys as well: of them this reads only the server's URL and passes on its scheme, host and port.
 * last_run is when the last monitoring run saved its state, after a push and after a failed one;
 * the agent keeps no other time of its runs.
 */

$etc = '/usr/local/etc/adminhelper';
$frp_conf = "$etc/frp/adminhelper.conf";
$monitor_conf = "$etc/monitor.conf";

/* The value of $key in a KEY="value" file, read as the agent reads it: the last one counts. */
function adminhelper_conf_value($path, $key)
{
    $value = '';
    $lines = @file($path, FILE_IGNORE_NEW_LINES);
    foreach ($lines === false ? [] : $lines as $line) {
        $parts = explode('=', trim($line), 2);
        if (count($parts) == 2 && trim($parts[0]) === $key) {
            $value = trim(trim($parts[1]), '"');
        }
    }
    return $value;
}

function adminhelper_origin($url)
{
    $parts = parse_url($url);
    if (!is_array($parts) || !isset($parts['scheme'], $parts['host'])) {
        return null;
    }
    $scheme = strtolower($parts['scheme']);
    if ($scheme !== 'https' && $scheme !== 'http') {
        return null;
    }
    return $scheme . '://' . $parts['host'] . (isset($parts['port']) ? ':' . $parts['port'] : '');
}

$server = adminhelper_origin(adminhelper_conf_value($frp_conf, 'ADMINHELPER_URL'));
if ($server === null) {
    $server = adminhelper_origin(adminhelper_conf_value($monitor_conf, 'MONITOR_URL'));
}

$version = null;
exec('/usr/local/bin/adminhelper-agent version 2>/dev/null', $out, $rc);
if ($rc == 0 && isset($out[0]) && preg_match('/^adminhelper-agent (\S+)$/', $out[0], $m)) {
    $version = $m[1];
}

$tunnel = 'none';
if (file_exists("$etc/frp/frpc.toml")) {
    exec('/usr/sbin/service adminhelper_frpc onestatus >/dev/null 2>&1', $ignored, $rc);
    $tunnel = $rc == 0 ? 'running' : 'stopped';
}

$last_run = @filemtime("$etc/.report-state.json");

echo json_encode([
    'registered' => file_exists($frp_conf) || file_exists($monitor_conf),
    'server' => $server,
    'version' => $version,
    'scheduled' => file_exists('/usr/local/etc/cron.d/adminhelper'),
    'tunnel' => $tunnel,
    'last_run' => $last_run === false ? null : $last_run,
]) . PHP_EOL;
