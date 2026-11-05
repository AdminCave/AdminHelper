// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Embedded RDP, stage 1: the backend (docs/features/arch-rdp-backend.md).

pub(crate) mod frame_ws;
#[cfg(test)]
mod license_gate;
pub(crate) mod tofu;
