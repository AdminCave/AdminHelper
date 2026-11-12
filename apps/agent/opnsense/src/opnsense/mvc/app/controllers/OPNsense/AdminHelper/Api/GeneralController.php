<?php

/*
 * SPDX-FileCopyrightText: 2026 Kevin Stenzel
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

namespace OPNsense\AdminHelper\Api;

use OPNsense\Base\ApiMutableModelControllerBase;

class GeneralController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'general';
    protected static $internalModelClass = 'OPNsense\AdminHelper\General';
}
