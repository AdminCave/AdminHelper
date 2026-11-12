<?php
// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Drops the web GUI certificate the firewall made on its first boot from a
// config.xml (argv[1]), so every lease of the template makes its own: with no
// system/webgui/ssl-certref, webgui_configure_do() creates a self-signed one at
// boot. Run by vm.py's OPNsense clean step, as root:
//
//   php forget-webgui-cert.php /conf/config.xml
//
// Exits 0 with the file rewritten, or unchanged if it names no certificate.
$path = $argv[1] ?? '';
$doc = new DOMDocument();
$doc->preserveWhiteSpace = true;
if ($path === '' || !$doc->load($path)) {
    fwrite(STDERR, "forget-webgui-cert: cannot read config.xml at '$path'\n");
    exit(1);
}
$xpath = new DOMXPath($doc);
$refs = $xpath->query('/opnsense/system/webgui/ssl-certref');
if ($refs->length === 0) {
    exit(0);
}
foreach (iterator_to_array($refs) as $ref) {
    $id = trim($ref->textContent);
    foreach (iterator_to_array($xpath->query('/opnsense/cert')) as $cert) {
        if (trim($xpath->evaluate('string(refid)', $cert)) === $id) {
            $cert->parentNode->removeChild($cert);
        }
    }
    $ref->parentNode->removeChild($ref);
}
exit($doc->save($path) === false ? 1 : 0);
