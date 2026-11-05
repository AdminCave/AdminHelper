// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! Detects a session whose picture stopped (docs/features/arch-rdp-backend.md, "Watchdog").
//! A pure state machine: the session feeds it the events and the time and acts on its verdict.

#![cfg_attr(not(test), expect(dead_code, reason = "the session in T5 uses it"))]

use std::time::{Duration, Instant};

/// How long a picture may take: the first one after a login, and the one that answers an input.
/// In the R-1074 probe the first picture came 0.4 to 1.9 s after the login, so 10 s is five times
/// the slowest case and still short enough that the user sees the session come back instead of
/// giving up on it.
const STALL: Duration = Duration::from_secs(10);

/// Reconnects in a row before the watchdog gives up. In the probe one of eight GFX runs stalled;
/// if stalls were independent, a fourth one in a row would happen in about one of 4000 sessions,
/// so it points to a cause that a reconnect does not remove.
const MAX_RECONNECTS: u32 = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Verdict {
    Ok,
    Reconnect,
    GiveUp,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Awaiting {
    FirstPicture,
    Answer,
}

#[derive(Debug, Default)]
pub(crate) struct Watchdog {
    awaiting: Option<(Awaiting, Instant)>,
    reconnects: u32,
}

impl Watchdog {
    pub(crate) fn login_complete(&mut self, now: Instant) {
        self.awaiting = Some((Awaiting::FirstPicture, now));
    }

    /// Only for input the desktop answers with a picture: a quiet desktop sends none, so any other
    /// input would look like a stall.
    pub(crate) fn input_sent(&mut self, now: Instant) {
        // A later input does not move the deadline of the first unanswered one.
        if self.awaiting.is_none() {
            self.awaiting = Some((Awaiting::Answer, now));
        }
    }

    pub(crate) fn frame(&mut self) {
        // Only an answered input shows that a reconnect helped: in the probe's stall the first
        // picture after the login came, and nothing after it.
        if let Some((Awaiting::Answer, _)) = self.awaiting {
            self.reconnects = 0;
        }
        self.awaiting = None;
    }

    pub(crate) fn tick(&mut self, now: Instant) -> Verdict {
        let Some((_, since)) = self.awaiting else {
            return Verdict::Ok;
        };
        if now.saturating_duration_since(since) <= STALL {
            return Verdict::Ok;
        }
        self.awaiting = None;
        if self.reconnects >= MAX_RECONNECTS {
            return Verdict::GiveUp;
        }
        self.reconnects += 1;
        Verdict::Reconnect
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MS: Duration = Duration::from_millis(1);

    fn logged_in(at: Instant) -> Watchdog {
        let mut watchdog = Watchdog::default();
        watchdog.login_complete(at);
        watchdog
    }

    /// One reconnect that stalls as in the probe: a first picture, then no answer to an input.
    fn stall_after_the_first_picture(watchdog: &mut Watchdog, now: &mut Instant) -> Verdict {
        watchdog.login_complete(*now);
        *now += Duration::from_secs(1);
        watchdog.frame();
        *now += Duration::from_secs(30);
        watchdog.input_sent(*now);
        *now += STALL;
        assert_eq!(watchdog.tick(*now), Verdict::Ok);
        *now += MS;
        watchdog.tick(*now)
    }

    #[test]
    fn watchdog_reconnects_without_a_first_picture() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        assert_eq!(watchdog.tick(t0 + STALL), Verdict::Ok);
        assert_eq!(watchdog.tick(t0 + STALL + MS), Verdict::Reconnect);
        // The reconnect is under way: nothing to wait for until its login.
        assert_eq!(watchdog.tick(t0 + STALL * 3), Verdict::Ok);
    }

    #[test]
    fn watchdog_keeps_a_session_whose_first_picture_comes_in_time() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        assert_eq!(watchdog.tick(t0 + STALL), Verdict::Ok);
        watchdog.frame();
        assert_eq!(watchdog.tick(t0 + STALL + MS), Verdict::Ok);
    }

    #[test]
    fn watchdog_reconnects_when_an_input_gets_no_picture() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        watchdog.frame();
        let t1 = t0 + Duration::from_secs(60);
        watchdog.input_sent(t1);
        assert_eq!(watchdog.tick(t1 + STALL), Verdict::Ok);
        assert_eq!(watchdog.tick(t1 + STALL + MS), Verdict::Reconnect);
    }

    #[test]
    fn watchdog_keeps_a_session_that_answers_its_input() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        watchdog.frame();
        let t1 = t0 + Duration::from_secs(60);
        watchdog.input_sent(t1);
        watchdog.frame();
        assert_eq!(watchdog.tick(t1 + STALL + MS), Verdict::Ok);
    }

    #[test]
    fn watchdog_a_later_input_does_not_move_the_deadline() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        watchdog.frame();
        let t1 = t0 + Duration::from_secs(60);
        watchdog.input_sent(t1);
        watchdog.input_sent(t1 + Duration::from_secs(5));
        assert_eq!(watchdog.tick(t1 + STALL + MS), Verdict::Reconnect);
    }

    #[test]
    fn watchdog_never_fires_on_a_quiet_desktop() {
        let t0 = Instant::now();
        let mut watchdog = logged_in(t0);
        watchdog.frame();
        for second in 1..=24 * 60 * 60 {
            let now = t0 + Duration::from_secs(second);
            assert_eq!(watchdog.tick(now), Verdict::Ok, "fired after {second} s");
        }
    }

    #[test]
    fn watchdog_gives_up_when_no_reconnect_brings_a_first_picture() {
        let mut now = Instant::now();
        let mut watchdog = Watchdog::default();
        for _ in 0..MAX_RECONNECTS {
            watchdog.login_complete(now);
            now += STALL + MS;
            assert_eq!(watchdog.tick(now), Verdict::Reconnect);
        }
        watchdog.login_complete(now);
        assert_eq!(watchdog.tick(now + STALL), Verdict::Ok);
        assert_eq!(watchdog.tick(now + STALL + MS), Verdict::GiveUp);
    }

    #[test]
    fn watchdog_gives_up_when_every_reconnect_stalls_after_its_first_picture() {
        let mut now = Instant::now();
        let mut watchdog = Watchdog::default();
        for _ in 0..MAX_RECONNECTS {
            assert_eq!(
                stall_after_the_first_picture(&mut watchdog, &mut now),
                Verdict::Reconnect
            );
        }
        assert_eq!(
            stall_after_the_first_picture(&mut watchdog, &mut now),
            Verdict::GiveUp
        );
    }

    #[test]
    fn watchdog_an_answered_input_resets_the_reconnects() {
        let mut now = Instant::now();
        let mut watchdog = Watchdog::default();
        for _ in 0..MAX_RECONNECTS {
            assert_eq!(
                stall_after_the_first_picture(&mut watchdog, &mut now),
                Verdict::Reconnect
            );
        }
        watchdog.login_complete(now);
        watchdog.frame();
        now += Duration::from_secs(30);
        watchdog.input_sent(now);
        watchdog.frame();
        for _ in 0..MAX_RECONNECTS {
            assert_eq!(
                stall_after_the_first_picture(&mut watchdog, &mut now),
                Verdict::Reconnect
            );
        }
        assert_eq!(
            stall_after_the_first_picture(&mut watchdog, &mut now),
            Verdict::GiveUp
        );
    }
}
