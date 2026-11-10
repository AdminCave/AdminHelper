// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! The hourly check of the device certificate while a sign-in lasts (R-1054). After a
//! rotation of the root or the intermediates the issuer names a new trust generation, and
//! a session that stays open renews within the hour instead of at half of the leaf's
//! lifetime. The sign-in itself checks first (`auth::login`).

use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tauri::Manager;

use crate::session::{SessionState, SignedIn};

/// How often a sign-in checks after its first check.
const INTERVAL: Duration = Duration::from_secs(60 * 60);

/// Managed state: an epoch counter, as for the notification stream. Each `start` bumps it,
/// and the task it spawns runs only while its epoch is the current one; `stop` bumps it too.
/// The epoch ends the task of a sign-in before even for a new sign-in of the same user,
/// which `SessionState::ensure_signed_in` lets pass.
pub type RenewalState = Arc<RenewalTask>;

#[derive(Default)]
pub struct RenewalTask {
    epoch: AtomicU64,
}

pub fn new_state() -> RenewalState {
    Arc::default()
}

/// Renews the enrolled identity if it is due (`enrollment::maybe_renew`) and logs why, or
/// why that failed. Best effort: the current certificate stays valid meanwhile.
pub async fn renew_if_due(server_url: &str) {
    match crate::enrollment::maybe_renew(server_url).await {
        Ok(Some(renewal)) => log::info!("mTLS client certificate renewed: {renewal}"),
        Ok(None) => {}
        // Logged, not silent: a renewal that fails for weeks (ca-issuer down, broken route)
        // would otherwise go unnoticed until the cert expires and locks the user out under
        // enforced mTLS. The warning lands in the diagnostics report (4.92).
        Err(e) => log::warn!(
            "renewing the mTLS client certificate failed (best effort, next try within the hour or at the next sign-in): {e}"
        ),
    }
}

/// Starts the hourly check for the session signed in now, on its server, and ends the one
/// of the sign-in before. Without a session nothing starts.
pub async fn start(app: tauri::AppHandle, state: RenewalState, session: &SessionState) {
    let Some(who) = session.current().await.map(|now| now.signed_in()) else {
        return;
    };
    let my_epoch = begin(&state);
    tauri::async_runtime::spawn(async move {
        let session = app.state::<SessionState>();
        let who = &who;
        run(&state, my_epoch, INTERVAL, session.inner(), who, || {
            renew_if_due(&who.server_url)
        })
        .await;
    });
}

/// Ends the task of the current sign-in at its next tick.
pub fn stop(state: &RenewalState) {
    state.epoch.fetch_add(1, Ordering::SeqCst);
}

/// The epoch of a new task.
fn begin(state: &RenewalTask) -> u64 {
    state.epoch.fetch_add(1, Ordering::SeqCst) + 1
}

/// Runs `check` every `interval` while the epoch is still `my_epoch` and `who` is still
/// signed in. The sign-in has just checked, so the first check comes after one interval.
async fn run<C, F>(
    state: &RenewalTask,
    my_epoch: u64,
    interval: Duration,
    session: &SessionState,
    who: &SignedIn,
    mut check: C,
) where
    C: FnMut() -> F,
    F: Future<Output = ()>,
{
    loop {
        tokio::time::sleep(interval).await;
        if state.epoch.load(Ordering::SeqCst) != my_epoch
            || session.ensure_signed_in(who).await.is_err()
        {
            return;
        }
        check().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::sync::atomic::AtomicUsize;

    use tokio::task::JoinHandle;
    use tokio::time::timeout;

    const TICK: Duration = Duration::from_millis(10);
    const PATIENCE: Duration = Duration::from_secs(5);

    async fn signed_in(session: &SessionState, user: &str) -> SignedIn {
        session
            .set(
                "https://198.51.100.7".to_string(),
                "access".to_string(),
                "refresh".to_string(),
                user.to_string(),
                false,
            )
            .await;
        session.current().await.unwrap().signed_in()
    }

    /// A task as `start` spawns it, every TICK, counting its checks.
    fn spawn_task(
        state: &RenewalState,
        session: &Arc<SessionState>,
        who: SignedIn,
        checks: &Arc<AtomicUsize>,
    ) -> JoinHandle<()> {
        let my_epoch = begin(state);
        let (state, session, checks) = (Arc::clone(state), Arc::clone(session), Arc::clone(checks));
        tokio::spawn(async move {
            run(&state, my_epoch, TICK, &session, &who, || {
                checks.fetch_add(1, Ordering::SeqCst);
                async {}
            })
            .await;
        })
    }

    async fn until(what: &str, done: impl Fn() -> bool) {
        timeout(PATIENCE, async {
            while !done() {
                tokio::time::sleep(TICK / 2).await;
            }
        })
        .await
        .unwrap_or_else(|_| panic!("{what} within {PATIENCE:?}"));
    }

    async fn ends(what: &str, task: JoinHandle<()>) {
        timeout(PATIENCE, task)
            .await
            .unwrap_or_else(|_| panic!("{what} within {PATIENCE:?}"))
            .unwrap();
    }

    #[tokio::test]
    async fn the_task_checks_every_interval_until_it_is_stopped() {
        let (state, session) = (new_state(), Arc::new(SessionState::default()));
        let who = signed_in(&session, "admin").await;
        let checks = Arc::new(AtomicUsize::new(0));

        let task = spawn_task(&state, &session, who, &checks);
        until("three checks", || checks.load(Ordering::SeqCst) >= 3).await;
        stop(&state);

        ends("the stopped task ends", task).await;
    }

    #[tokio::test]
    async fn a_sign_out_ends_the_task() {
        let (state, session) = (new_state(), Arc::new(SessionState::default()));
        let who = signed_in(&session, "admin").await;
        let checks = Arc::new(AtomicUsize::new(0));

        let task = spawn_task(&state, &session, who, &checks);
        until("a check", || checks.load(Ordering::SeqCst) >= 1).await;
        // The session alone ends it, as after a failed token renewal: nobody stops the task.
        session.take().await;

        ends("the task of the signed out session ends", task).await;
    }

    #[tokio::test]
    async fn a_new_sign_in_ends_the_task_of_the_one_before() {
        let (state, session) = (new_state(), Arc::new(SessionState::default()));
        let before = signed_in(&session, "admin").await;
        let old_checks = Arc::new(AtomicUsize::new(0));
        let old = spawn_task(&state, &session, before, &old_checks);
        until("a check of the first sign-in", || {
            old_checks.load(Ordering::SeqCst) >= 1
        })
        .await;

        // The same user again: `ensure_signed_in` lets the old task pass, the epoch does not.
        let again = signed_in(&session, "admin").await;
        let new_checks = Arc::new(AtomicUsize::new(0));
        let new = spawn_task(&state, &session, again, &new_checks);

        ends("the task of the sign-in before ends", old).await;
        let seen = old_checks.load(Ordering::SeqCst);
        until("two checks of the new sign-in", || {
            new_checks.load(Ordering::SeqCst) >= 2
        })
        .await;
        assert_eq!(old_checks.load(Ordering::SeqCst), seen);
        stop(&state);
        ends("the stopped task ends", new).await;
    }
}
