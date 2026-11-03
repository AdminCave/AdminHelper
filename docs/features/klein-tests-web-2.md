<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-web-2 — Spec

Zug der Klein-Session (Roadmap R-1108).

## Problem
R-1108: `expect.toHaveScreenshot.maxDiffPixelRatio` steht auf 0.02 (`apps/web/playwright.config.ts:69`). Bei 1280×720
sind das ~18 400 Pixel; auf dunklen Seiten besteht damit eine grobe Umgestaltung (6 von 7 alten Baselines gegen das neue
Design, reviewer kern-web-4 T8). Der Visual-Diff fängt dann nur noch Totalschäden.

## Ziel
Toleranz auf 0.005 (~4 600 Pixel). Messung 2026-11-03 auf der Dev-Box (Chromium 1223, 3 Wiederholungen je Seite):
das Rendering ist reproduzierbar, weicht von den Baselines aber um 67–4028 Pixel (≤ 0.44 %) ab (Font-/Raster-Unterschied
Host gegen CI); 0.005 lässt dieses Rauschen durch und ist 4× enger als heute. Die CI (`frontend_e2e`, Baselines
dort erzeugt) ist der Beleg. Wird sie damit rot, steigt der Wert auf 0.01 (Fallback, im Ledger vermerkt).
Nicht-Ziel: Baselines neu erzeugen, Masken, Per-Test-Schwellen (YAGNI).

## Doku-Impact
`docs/developer/webui.html` + `docs/en/developer/webui.html` nennen die Toleranz (0.02): nachziehen.

## Risiken
Zu eng ⇒ flaky `frontend_e2e` (CI retries 2). Rollback: Wert zurück.
