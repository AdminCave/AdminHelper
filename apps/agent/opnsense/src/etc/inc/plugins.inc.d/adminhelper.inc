<?php

/*
 * SPDX-FileCopyrightText: 2026 Kevin Stenzel
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

function adminhelper_enabled()
{
    return (string)(new \OPNsense\AdminHelper\General())->enabled == '1';
}

/*
 * The tunnel client is a service only while the agent has a tunnel for it: the agent writes
 * frpc.toml with the first tunnel the server sends and removes it with the last. The pidfile is
 * the one daemon(8) keeps for frpc itself, so a client that keeps failing does not count as
 * running.
 */
function adminhelper_services()
{
    $services = [];

    if (!adminhelper_enabled() || !file_exists('/usr/local/etc/adminhelper/frp/frpc.toml')) {
        return $services;
    }

    $services[] = [
        'description' => gettext('AdminHelper tunnel client'),
        'configd' => [
            'restart' => ['adminhelper restart'],
            'start' => ['adminhelper start'],
            'stop' => ['adminhelper stop'],
        ],
        'name' => 'adminhelper_frpc',
        'pidfile' => '/var/run/adminhelper_frpc.child.pid',
    ];

    return $services;
}
