<?php

/*
 * SPDX-FileCopyrightText: 2026 Kevin Stenzel
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

namespace OPNsense\AdminHelper;

use OPNsense\Base\IndexController;

class GeneralController extends IndexController
{
    public function indexAction()
    {
        $this->view->pick('OPNsense/AdminHelper/general');
        $this->view->generalForm = $this->getForm('general');
    }
}
