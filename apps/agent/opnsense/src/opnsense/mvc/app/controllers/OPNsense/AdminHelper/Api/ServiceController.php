<?php

/*
 * SPDX-FileCopyrightText: 2026 Kevin Stenzel
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

namespace OPNsense\AdminHelper\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Base\UserException;
use OPNsense\Core\Backend;

class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceClass = '\OPNsense\AdminHelper\General';
    protected static $internalServiceEnabled = 'enabled';
    protected static $internalServiceTemplate = 'OPNsense/AdminHelper';
    protected static $internalServiceName = 'adminhelper';

    /*
     * The switch governs two things, the agent's schedule and the tunnel client, so the base
     * class's stop, template, start does not fit: reconfigure.sh sets both after the template has
     * written the tunnel client's rcvar, and leaves a running tunnel client running.
     */
    public function reconfigureAction()
    {
        $result = ['status' => 'failed'];

        if ($this->request->isPost()) {
            $backend = new Backend();
            if (trim($backend->configdpRun('template reload', [static::$internalServiceTemplate])) !== 'OK') {
                throw new UserException(
                    gettext('Template generation failed for AdminHelper. See the backend log for details.'),
                    gettext('Configuration exception')
                );
            }
            $state = $this->serviceEnabled() ? 'on' : 'off';
            if (trim($backend->configdpRun('adminhelper reconfigure', [$state])) === 'OK') {
                $result['status'] = 'ok';
            } else {
                $result['status_msg'] = sprintf(gettext('AdminHelper could not be turned %s.'), $state);
            }
        }

        return $result;
    }

    /*
     * The agent's state for the settings page; info.php passes on no field that holds a secret.
     */
    public function infoAction()
    {
        $info = json_decode((new Backend())->configdRun('adminhelper info'), true);

        return is_array($info) ? $info : [];
    }
}
