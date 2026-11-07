# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Incidents of the bell (R-1079, docs/features/arch-notify-incidents.md).

The hub folds the events of one check into one incident instead of writing a row per
event. A problem whose key an active incident carries for the same server folds into
it; one whose incident was resolved inside REOPEN_WINDOW of its last ping reopens it
silently; anything else opens a new one, and the new keys of one bundle open one bundle
incident together. The server is part of the match: a check moved to another server
starts a new incident there, so nobody reads the history of a server they do not see.
Every recipient keeps one row per incident, which a ping moves up (unread, notified_at,
outbox); a silent fold changes only the incident and its history.

Whether an event pings is the rule the monitoring service applied before
(hub_decision in apps/monitoring/app/alerter.py): a new incident, a shown warning that
turns critical, or no problem ping inside REOPEN_WINDOW. A recovery resolves the
incident and pings only if the bell showed its problem, at the level it showed it.

Events without a key (the server's own notices, an older monitoring sender) open one
incident each at warning/critical, and only when somebody receives it; they never
resolve by themselves. Info notices, keyless recoveries and keyless bundles stay
rows without an incident, as before: a bundle without keys has no members to hold its
servers, and a team action checks those.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.core import config
from app.core.time import iso_utc
from app.modules.notifications import stream_hub
from app.modules.notifications.models import (
    Notification,
    NotificationIncident,
    NotificationIncidentEvent,
    NotificationIncidentMember,
    NotificationOutbox,
    NotificationServerMute,
    NotificationSettings,
)
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import _bundle_text, channels_for, resolve_recipients
from app.modules.servers.models import Server
from app.modules.users.models import User

# The same span as HUB_COOLDOWN of the monitoring service, whose cooldown moved here.
REOPEN_WINDOW = timedelta(minutes=30)
HISTORY_MAX = 200
TEXT_MAX = 2000
ACTIVE = ("open", "acked")

# The levels of apps/monitoring/app/alerter.py.
_STATUS_LEVEL = {"ok": 0, "info": 0, "pending": 0, "unknown": 1, "warning": 1, "critical": 2}
_SEVERITY_LEVEL = {"info": 0, "warning": 1, "critical": 2}
_LEVEL_SEVERITY = {0: "info", 1: "warning", 2: "critical"}

_Incident = NotificationIncident
_Member = NotificationIncidentMember
_Entry = NotificationIncidentEvent
# What the history cap may drop: the hub's own entries, never a note, an
# acknowledgement or a step a person took.
_AUTOMATIC = or_(
    _Entry.kind.in_(("triggered", "notified", "escalated")),
    and_(_Entry.kind.in_(("resolved", "reopened")), _Entry.actor_id.is_(None)),
)

Recipients = list[tuple[User, dict[str, list[str]]]]


@dataclass
class Ingested:
    """What one ingest did. notified: the recipient rows its pings wrote, muted ones
    included. pinged_servers: the servers of the incidents that got a problem ping
    (the router fires alert.triggered for them)."""

    notified: int = 0
    pinged_servers: list[str | None] = field(default_factory=list)
    user_ids: set[int] = field(default_factory=set)
    max_id: int = 0
    incident_ids: set[int] = field(default_factory=set)


@dataclass
class _Target:
    incident: NotificationIncident
    bundle: bool
    new: bool = False
    reopened: bool = False
    keys: list[str] = field(default_factory=list)


def level_of(event: IncomingEvent) -> int:
    """The level of the status the event moved to, capped at the check's severity. The
    hub reads the cap off severity: the worse of old and new, already capped."""
    severity = _SEVERITY_LEVEL[event.severity]
    if event.new_status is None:
        return severity
    return min(_STATUS_LEVEL.get(event.new_status, 1), severity)


def ingest(db: Session, event: IncomingEvent, *, now: datetime | None = None) -> Ingested:
    """Fold one event into the incidents, ping whom its rule says, commit once."""
    now = now or datetime.now(timezone.utc)
    done = Ingested()
    keyed = event.incident_key is not None or event.incident_keys is not None
    recovery = event.new_status == "ok"
    level = level_of(event)
    if keyed and recovery:
        _recover(db, event, now, done)
    elif keyed:
        # A problem at capped level info: hub_decision never let it through.
        if level > 0:
            _problem(db, event, level, now, done)
    elif recovery or level == 0:
        _plain(db, event, resolve_recipients(db, event), done)
    else:
        done.pinged_servers = _servers(event) or [event.source_id]
        _keyless(db, event, resolve_recipients(db, event), now, done)
    _finish(db, done)
    return done


def notify(
    db: Session, users: Iterable[User], event: IncomingEvent, *, now: datetime | None = None
) -> int:
    """The bell rows of a notice whose recipients the caller chose (service.notify_users):
    keyless, no outbox. Commits only when there is a row to write."""
    now = now or datetime.now(timezone.utc)
    unique: dict[int, User] = {}
    for user in users:
        unique.setdefault(user.id, user)
    recipients: Recipients = [(user, {"bell": []}) for user in unique.values()]
    if not recipients:
        return 0
    done = Ingested()
    if event.new_status == "ok" or level_of(event) == 0:
        _plain(db, event, recipients, done)
    else:
        _keyless(db, event, recipients, now, done)
    _finish(db, done)
    return done.notified


# --- the three kinds of events ---------------------------------------------------


def _plain(db: Session, event: IncomingEvent, recipients: Recipients, done: Ingested) -> None:
    for user, channels in recipients:
        title, body = _text(event, channels["bell"])
        row = Notification(
            user_id=user.id,
            severity=event.severity,
            category=event.category,
            event_type=event.event_type,
            title=title,
            body=body,
            source_type=event.source_type,
            source_id=event.source_id,
        )
        db.add(row)
        db.flush()  # the id for the outbox FK
        _queue(db, row, user, channels, event, "ok" if event.new_status == "ok" else event.severity)
        done.notified += 1
        done.user_ids.add(user.id)
        done.max_id = max(done.max_id, row.id)


def _keyless(
    db: Session, event: IncomingEvent, recipients: Recipients, now: datetime, done: Ingested
) -> None:
    if event.source_ids is not None:
        _plain(db, event, recipients, done)
        return
    # Only with a recipient: notify_expiring tries a notice nobody got again on every
    # run, each try would leave an incident nobody sees.
    if not recipients:
        return
    incident = _Incident(
        key=None,
        state="open",
        severity=event.severity,
        event_count=1,
        first_at=now,
        last_at=now,
    )
    _take_text(incident, event, event.source_id)
    db.add(incident)
    db.flush()
    target = _Target(incident, bundle=False, new=True)
    _log(db, done, incident, "triggered", now, text=_event_text(event), severity=event.severity)
    _ping(db, target, event, recipients, now, done, severity=event.severity, problem=True)


def _problem(db: Session, event: IncomingEvent, level: int, now: datetime, done: Ingested) -> None:
    pairs = _pairs(event)
    _lock(db, list(pairs))
    window = _Incident.state.in_(ACTIVE) | and_(
        _Incident.state == "resolved", _Incident.last_notified_at > now - REOPEN_WINDOW
    )
    incidents, members = _containing(db, list(pairs), window)
    targets: dict[int, _Target] = {}
    fresh: list[str] = []
    for key in pairs:
        server = pairs[key]
        active = [i for i in incidents if i.state in ACTIVE]
        incident = _latest(key, server, active, members) or _latest(key, server, incidents, members)
        if incident is None:
            fresh.append(key)
            continue
        target = targets.get(incident.id)
        if target is None:
            target = targets[incident.id] = _Target(incident, bundle=incident.id in members)
        if incident.state == "resolved":
            incident.state = "open"
            incident.resolved_at = incident.resolved_by = None
            incident.acked_at = incident.acked_by = None
            target.reopened = True
        member = members.get(incident.id, {}).get(key)
        if member is not None:
            member.recovered_at = None
        target.keys.append(key)

    if fresh:
        bundle = event.incident_keys is not None
        incident = _Incident(
            key=None if bundle else fresh[0],
            state="open",
            severity=_LEVEL_SEVERITY[level],
            event_count=0,
            first_at=now,
            last_at=now,
        )
        _take_text(incident, event, None if bundle else pairs[fresh[0]])
        db.add(incident)
        db.flush()
        if bundle:
            db.add_all(_Member(incident_id=incident.id, key=k, server_id=pairs[k]) for k in fresh)
        targets[incident.id] = _Target(incident, bundle=bundle, new=True, keys=fresh)

    severity = _LEVEL_SEVERITY[level]
    for target in targets.values():
        incident = target.incident
        incident.event_count += 1
        incident.last_at = now
        if target.bundle and not (target.new or target.reopened):
            incident.severity = _LEVEL_SEVERITY[max(level, _SEVERITY_LEVEL[incident.severity])]
        else:
            incident.severity = severity
        # A single event folding into a bundle names its own server: the bundle keeps
        # the team text of its bundle events, which the other members' readers see.
        if not target.bundle or event.source_ids is not None:
            _take_text(incident, event, None if target.bundle else pairs[target.keys[0]])
        for key in target.keys:
            _log(
                db,
                done,
                incident,
                "reopened" if target.reopened else "triggered",
                now,
                text=_event_text(event),
                severity=severity,
                server_id=pairs[key] if target.bundle else None,
            )

        escalated = incident.notified_severity == "warning" and level == 2
        expired = (
            incident.last_notified_at is None or now - incident.last_notified_at >= REOPEN_WINDOW
        )
        if not (target.new or escalated or expired):
            continue
        if escalated:
            if incident.state == "acked":
                incident.state = "open"
                incident.acked_at = incident.acked_by = None
            _log(db, done, incident, "escalated", now, severity=severity)
        ping_event = _ping_event(event, [pairs[k] for k in target.keys])
        servers = _servers(ping_event) or [ping_event.source_id]
        done.pinged_servers.extend(servers)
        recipients = resolve_recipients(db, ping_event)
        _ping(db, target, ping_event, recipients, now, done, severity=severity, problem=True)


def _recover(db: Session, event: IncomingEvent, now: datetime, done: Ingested) -> None:
    pairs = _pairs(event)
    keys = list(pairs)
    _lock(db, keys)
    incidents, members = _containing(db, keys, _Incident.state.in_(ACTIVE))
    targets: dict[int, _Target] = {}
    stale: list[str] = []
    for key in keys:
        incident = _latest(key, pairs[key], incidents, members)
        if incident is None:
            stale.append(key)
            continue
        target = targets.get(incident.id)
        if target is None:
            target = targets[incident.id] = _Target(incident, bundle=incident.id in members)
        target.keys.append(key)

    for target in targets.values():
        incident = target.incident
        incident.last_at = now
        if target.bundle:
            for key in target.keys:
                member = members[incident.id][key]
                if member.recovered_at is None:
                    member.recovered_at = now
                _log(
                    db,
                    done,
                    incident,
                    "resolved",
                    now,
                    text=_event_text(event),
                    server_id=pairs[key],
                )
            if any(m.recovered_at is None for m in members[incident.id].values()):
                continue
        incident.state = "resolved"
        incident.resolved_at = now
        incident.resolved_by = None
        _log(
            db,
            done,
            incident,
            "resolved",
            now,
            text=None if target.bundle else _event_text(event),
            severity="ok",
        )
        # The bell clears only what it showed, at the level it showed it: lowered in
        # between, a subscriber with min_severity critical would miss the all-clear.
        shown = incident.notified_severity
        if shown not in ("warning", "critical"):
            continue
        if target.bundle:
            servers = [m.server_id for m in members[incident.id].values()]
            ping_event = _bundle_all_clear(event, incident, servers, shown)
        else:
            ping_event = _ping_event(event, [pairs[k] for k in target.keys]).model_copy(
                update={"severity": shown}
            )
        recipients = resolve_recipients(db, ping_event)
        _ping(db, target, ping_event, recipients, now, done, severity="ok", problem=False)

    if stale:
        _note_stale(db, stale, pairs, event, now, done)


def _note_stale(
    db: Session,
    keys: list[str],
    pairs: dict[str, str | None],
    event: IncomingEvent,
    now: datetime,
    done: Ingested,
) -> None:
    """A recovery without an active incident (resolved by hand, or never opened): a
    silent entry on the latest incident of the key on its server, nothing else."""
    latest: dict[str, int] = {}
    for key, server, iid in (
        db.query(_Incident.key, _Incident.source_id, func.max(_Incident.id))
        .filter(_Incident.key.in_(keys))
        .group_by(_Incident.key, _Incident.source_id)
    ):
        if server == pairs[key]:
            latest[key] = iid
    for key, server, iid in (
        db.query(_Member.key, _Member.server_id, func.max(_Member.incident_id))
        .filter(_Member.key.in_(keys))
        .group_by(_Member.key, _Member.server_id)
    ):
        if server == pairs[key]:
            latest[key] = max(iid, latest.get(key, 0))
    if not latest:
        return
    incidents = {
        i.id: i
        for i in db.query(_Incident)
        .filter(_Incident.id.in_(set(latest.values())))
        .order_by(_Incident.id)
        .with_for_update()
    }
    members = {
        (m.incident_id, m.key): m
        for m in db.query(_Member).filter(
            _Member.incident_id.in_(set(latest.values())), _Member.key.in_(keys)
        )
    }
    for key, iid in latest.items():
        member = members.get((iid, key))
        if member is not None and member.recovered_at is None:
            member.recovered_at = now
        _log(
            db,
            done,
            incidents[iid],
            "resolved",
            now,
            text=_event_text(event),
            server_id=pairs[key] if member is not None else None,
        )


# --- the ping ----------------------------------------------------------------------


def _ping(
    db: Session,
    target: _Target,
    event: IncomingEvent,
    recipients: Recipients,
    now: datetime,
    done: Ingested,
    *,
    severity: str,
    problem: bool,
) -> None:
    """Write every recipient's row of the incident anew: unread, moved up by
    notified_at, outbox entries with the text of this ping. A muted row (the incident
    until a time, or the one server of the ping) takes the content only, stays read
    and sends nothing. severity: what the bell shows afterwards (notified_severity)."""
    incident = target.incident
    rows = {
        row.user_id: row
        for row in db.query(Notification).filter(Notification.incident_id == incident.id)
    }
    server = _single_server(event)
    muted_by_server: set[int] = set()
    if server is not None and recipients:
        muted_by_server = {
            uid
            for (uid,) in db.query(NotificationServerMute.user_id).filter(
                NotificationServerMute.server_id == server,
                NotificationServerMute.until > now,
                NotificationServerMute.user_id.in_([user.id for user, _ in recipients]),
            )
        }
    used: list[str] = []
    for user, channels in recipients:
        row = rows.get(user.id)
        muted = user.id in muted_by_server or (
            row is not None and row.muted_until is not None and row.muted_until > now
        )
        if row is None:
            row = Notification(
                user_id=user.id,
                incident_id=incident.id,
                notified_at=now,
                read_at=now if muted else None,
            )
            db.add(row)
        title, body = _text(event, channels["bell"])
        row.severity = event.severity
        row.category = event.category
        row.event_type = event.event_type
        row.title = title
        row.body = body
        row.source_type = event.source_type
        # A bundle ping of one server is that server's (_single_server): the feed and
        # the badge read the server mute from the row, as this ping applied it.
        row.source_id = server if event.source_ids is not None else event.source_id
        if not muted:
            row.read_at = None
            row.hidden_at = None
            row.notified_at = now
        db.flush()
        if not muted:
            for channel in ("bell", *_queue(db, row, user, channels, event, severity)):
                if channel not in used:
                    used.append(channel)
        done.notified += 1
        done.user_ids.add(user.id)
        done.max_id = max(done.max_id, row.id)
    if problem:
        incident.last_notified_at = now
    incident.notified_severity = severity
    if used:
        _log(db, done, incident, "notified", now, text=", ".join(used))


def _queue(
    db: Session,
    row: Notification,
    user: User,
    channels: dict[str, list[str]],
    event: IncomingEvent,
    level: str,
) -> list[str]:
    """Outbox entries for the external channels the person's matrix picks for `level`
    (the severity of this ping, ok for the all-clear) and they have an address for.
    Each carries the text of this ping, naming the servers of the bell row: a later
    ping rewrites the row. Nothing without "out" (a notice of notify)."""
    if "out" not in channels:
        return []
    settings = db.get(NotificationSettings, user.id)
    picked = channels_for(settings, level, event.category)
    title, body = _text(event, channels["out"])
    queued = []
    targets = (
        ("email", user.email),
        ("ntfy", settings.ntfy_url if settings else None),
        ("telegram", user.telegram_chat_id if config.TELEGRAM_BOT_TOKEN else None),
        ("webhook", settings.webhook_url if settings else None),
    )
    for channel, address in targets:
        if channel not in picked or not address:
            continue
        db.add(
            NotificationOutbox(
                notification_id=row.id,
                user_id=user.id,
                channel=channel,
                address=address,
                title=title,
                body=body,
                severity=level,
            )
        )
        queued.append(channel)
    return queued


# --- helpers -----------------------------------------------------------------------


def _pairs(event: IncomingEvent) -> dict[str, str | None]:
    """key -> server of the event, in event order; a repeated key counts once."""
    if event.incident_keys is not None:
        pairs: dict[str, str | None] = {}
        for key, server in zip(event.incident_keys, event.source_ids or []):
            pairs.setdefault(key, server)
        return pairs
    return {event.incident_key: event.source_id}


def _lock(db: Session, keys: list[str]) -> None:
    """Serialise the ingests of a key: two events of one check would both miss the
    active incident and open two. Taken in hash order, so two bundles sharing keys
    never wait on each other in a circle."""
    hashes = db.execute(
        text("SELECT DISTINCT hashtext(k) AS h FROM unnest(CAST(:keys AS text[])) AS k ORDER BY h"),
        {"keys": keys},
    ).scalars()
    for h in list(hashes):
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('adminhelper.incident'), :h)"), {"h": h}
        )


def _containing(
    db: Session, keys: list[str], condition
) -> tuple[list[NotificationIncident], dict[int, dict[str, NotificationIncidentMember]]]:
    """The incidents under condition that carry one of the keys, as key or as member,
    locked in id order; and the members of the bundles among them by key."""
    member_of = select(_Member.incident_id).where(_Member.key.in_(keys))
    incidents = (
        db.query(_Incident)
        .filter(or_(_Incident.key.in_(keys), _Incident.id.in_(member_of)), condition)
        .order_by(_Incident.id)
        .with_for_update()
        .all()
    )
    members: dict[int, dict[str, NotificationIncidentMember]] = {}
    if incidents:
        for member in (
            db.query(_Member)
            .filter(_Member.incident_id.in_([i.id for i in incidents]))
            .order_by(_Member.incident_id, _Member.server_id)
        ):
            members.setdefault(member.incident_id, {})[member.key] = member
    return incidents, members


def _latest(
    key: str, server: str | None, incidents: list[NotificationIncident], members: dict
) -> NotificationIncident | None:
    """The newest of the incidents that holds the key for this server."""
    for incident in reversed(incidents):
        member = members.get(incident.id, {}).get(key)
        if (member is not None and member.server_id == server) or (
            incident.key == key and incident.source_id == server
        ):
            return incident
    return None


def _servers(event: IncomingEvent) -> list[str | None]:
    if event.source_ids is not None:
        return list(dict.fromkeys(event.source_ids))
    return []


def _single_server(event: IncomingEvent) -> str | None:
    """The server a person's server mute applies to: the one server of the ping."""
    if event.source_type != "server":
        return None
    if event.source_ids is not None:
        ids = set(event.source_ids)
        return ids.pop() if len(ids) == 1 else None
    return event.source_id


def _ping_event(event: IncomingEvent, servers: list[str | None]) -> IncomingEvent:
    """The event as one incident's ping: a bundle names only this incident's servers."""
    if event.source_ids is None:
        return event
    return event.model_copy(update={"source_ids": servers, "incident_keys": None})


def _bundle_all_clear(
    event: IncomingEvent, incident: NotificationIncident, servers: list[str], shown: str
) -> IncomingEvent:
    """The all-clear of a bundle over all its members. A single event that completes
    it names its own server, which other readers of the bundle may not see: its
    all-clear is the bundle's own title marked resolved, with the server lines alone
    (the bundle's body describes the problem)."""
    update: dict = {
        "severity": shown,
        "source_id": None,
        "source_ids": servers,
        "incident_key": None,
        "incident_keys": None,
    }
    if event.source_ids is None:
        update.update(
            title=f"Resolved: {incident.title}", body=None, source_type=incident.source_type
        )
    return event.model_copy(update=update)


def _text(event: IncomingEvent, servers: list[str]) -> tuple[str, str | None]:
    if event.source_ids is not None:
        return _bundle_text(event, servers)
    return event.title, event.body


def _event_text(event: IncomingEvent) -> str:
    return f"{event.title}\n{event.body}" if event.body else event.title


def _take_text(incident: NotificationIncident, event: IncomingEvent, source_id: str | None) -> None:
    """The incident shows its last problem event. source_id: the incident's server
    (a single incident fed by a bundle event names its own), NULL for a bundle."""
    incident.category = event.category
    incident.event_type = event.event_type
    incident.title = event.title
    incident.body = event.body
    incident.source_type = event.source_type
    incident.source_id = source_id
    incident.rules = (
        json.dumps([rule.model_dump() for rule in event.rules]) if event.rules is not None else None
    )


def _log(
    db: Session,
    done: Ingested,
    incident: NotificationIncident,
    kind: str,
    now: datetime,
    *,
    text: str | None = None,
    severity: str | None = None,
    server_id: str | None = None,
) -> None:
    db.add(
        _Entry(
            incident_id=incident.id,
            at=now,
            kind=kind,
            text=text[:TEXT_MAX] if text else None,
            severity=severity,
            server_id=server_id,
        )
    )
    done.incident_ids.add(incident.id)


def _cap_history(db: Session, incident_ids: Iterable[int]) -> None:
    db.flush()
    for incident_id in incident_ids:
        count = db.query(func.count(_Entry.id)).filter(_Entry.incident_id == incident_id).scalar()
        excess = count - HISTORY_MAX
        if excess <= 0:
            continue
        oldest = (
            select(_Entry.id)
            .where(_Entry.incident_id == incident_id, _AUTOMATIC)
            .order_by(_Entry.id)
            .limit(excess)
        )
        db.query(_Entry).filter(_Entry.id.in_(oldest)).delete(synchronize_session=False)


def _finish(db: Session, done: Ingested) -> None:
    _cap_history(db, done.incident_ids)
    db.commit()
    # After commit (rows are now readable), a refresh nudge to the live SSE streams of
    # the users across all workers. Best-effort; polling reconciles.
    if done.user_ids:
        stream_hub.publish(sorted(done.user_ids), done.max_id)


# --- the API: what a reader sees and may do (router.py) ----------------------------

# The transitions of the team actions: the states each one leaves from.
_FROM = {"acked": ("open",), "resolved": ("open", "acked"), "reopened": ("resolved",), "note": None}


@dataclass
class Access:
    """A reader's hold on an incident: their own row, the members of a bundle, the
    servers of the incident they see now, and whether they see every one (can_act:
    the team actions)."""

    row: Notification
    incident: NotificationIncident
    members: list[NotificationIncidentMember]
    visible: set[str]
    can_act: bool


def access(db: Session, user: User, incident_id: int, *, lock: bool = False) -> Access | None:
    """None without a row of the reader's own or without sight of a server of the
    incident now: the API answers 404 to both alike. lock: the team actions hold the
    incident row until their commit."""
    row = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.incident_id == incident_id)
        .one_or_none()
    )
    if row is None:
        return None
    query = db.query(_Incident).filter(_Incident.id == incident_id)
    if lock:
        query = query.with_for_update()
    incident = query.one_or_none()
    if incident is None:
        return None
    members = (
        db.query(_Member)
        .filter(_Member.incident_id == incident_id)
        .order_by(_Member.server_id, _Member.key)
        .all()
    )
    sight = _sight(
        user, _assigned(user), _incident_servers(incident, [m.server_id for m in members])
    )
    if sight is None:
        return None
    return Access(row, incident, members, *sight)


def may_act(kind: str, state: str) -> bool:
    allowed = _FROM[kind]
    return allowed is None or state in allowed


def act(
    db: Session, user: User, held: Access, kind: str, now: datetime, *, text: str | None = None
) -> None:
    """A team action on an incident held by access(lock=True): the transition and its
    history entry, which names the actor."""
    incident = held.incident
    if kind == "acked":
        incident.state = "acked"
        incident.acked_by, incident.acked_at = user.id, now
    elif kind == "resolved":
        incident.state = "resolved"
        incident.resolved_by, incident.resolved_at = user.id, now
    elif kind == "reopened":
        incident.state = "open"
        incident.resolved_by = incident.resolved_at = None
        incident.acked_by = incident.acked_at = None
    db.add(_Entry(incident_id=incident.id, at=now, kind=kind, actor_id=user.id, text=text))


def finish_actions(db: Session, incident_ids: list[int]) -> None:
    """Commit the team actions, then nudge every holder of a row of these incidents:
    the state they show changed for all of them."""
    if not incident_ids:
        return
    _cap_history(db, incident_ids)
    db.commit()
    holders = (
        db.query(Notification.user_id, func.max(Notification.id))
        .filter(Notification.incident_id.in_(incident_ids))
        .group_by(Notification.user_id)
        .all()
    )
    if holders:
        stream_hub.publish(sorted(uid for uid, _ in holders), max(mid for _, mid in holders))


def feed_rows(db: Session, user: User, rows: list[Notification], now: datetime) -> list[dict]:
    """The rows as the feed hands them out. The team state of an incident (incidentId
    included) only while the reader still sees one of its servers, as for its detail;
    muted: whichever of the reader's mutes holds the row now."""
    ids = {row.incident_id for row in rows if row.incident_id is not None}
    found: dict[int, NotificationIncident] = {}
    servers: dict[int, list[str]] = {}
    if ids:
        found = {i.id: i for i in db.query(_Incident).filter(_Incident.id.in_(ids))}
        for incident_id, server_id in (
            db.query(_Member.incident_id, _Member.server_id)
            .filter(_Member.incident_id.in_(ids))
            .order_by(_Member.incident_id, _Member.server_id)
        ):
            servers.setdefault(incident_id, []).append(server_id)
    assigned = _assigned(user)
    seen = {
        iid: incident
        for iid, incident in found.items()
        if _sight(user, assigned, _incident_servers(incident, servers.get(iid, []))) is not None
    }
    names = _usernames(db, [u for i in seen.values() for u in (i.acked_by, i.resolved_by)])
    mutes = {m.server_id: m.until for m in server_mutes(db, user, now)} if ids else {}
    out = []
    for row in rows:
        incident = seen.get(row.incident_id)
        item = row.to_dict()
        item.update(
            incidentId=incident.id if incident else None,
            state=incident.state if incident else None,
            count=incident.event_count if incident else None,
            ackedBy=names.get(incident.acked_by) if incident else None,
            resolvedBy=names.get(incident.resolved_by) if incident else None,
            notifiedAt=iso_utc(row.notified_at),
            **_mute(row, mutes, now),
        )
        out.append(item)
    return out


def detail(db: Session, user: User, held: Access, now: datetime) -> dict:
    """The incident as its reader may see it: the servers among its own they see now,
    the history without entries of the others, a bundle's title and lines counting
    only theirs."""
    incident = held.incident
    bundle = bool(held.members)
    recovered: dict[str, list[datetime | None]] = {}
    if bundle:
        for member in held.members:
            if member.server_id in held.visible:
                recovered.setdefault(member.server_id, []).append(member.recovered_at)
    else:
        recovered = {sid: [None] for sid in _incident_servers(incident, []) if sid in held.visible}
    labels = {
        s.id: s.name for s in db.query(Server).filter(Server.id.in_(list(recovered))) if s.name
    }
    servers = [
        {
            "id": sid,
            "name": labels.get(sid, sid),
            "recoveredAt": None if None in ats else iso_utc(max(ats)),
        }
        for sid, ats in recovered.items()
    ]
    if bundle:
        # _bundle_text reads title and body only, which the incident carries too.
        title, body = _bundle_text(incident, [s["name"] for s in servers])
    else:
        title, body = incident.title, incident.body
    entries = (
        db.query(_Entry)
        .filter(
            _Entry.incident_id == incident.id,
            or_(_Entry.server_id.is_(None), _Entry.server_id.in_(held.visible)),
        )
        .order_by(_Entry.id)
        .all()
    )
    names = _usernames(
        db, [incident.acked_by, incident.resolved_by, *(e.actor_id for e in entries)]
    )
    used = {
        channel
        for (channel,) in db.query(NotificationOutbox.channel)
        .filter(NotificationOutbox.notification_id == held.row.id)
        .distinct()
    }
    return {
        "id": incident.id,
        "state": incident.state,
        "severity": incident.severity,
        "category": incident.category,
        "eventType": incident.event_type,
        "title": title,
        "body": body,
        "sourceType": incident.source_type,
        "sourceId": incident.source_id,
        "count": incident.event_count,
        "firstAt": iso_utc(incident.first_at),
        "lastAt": iso_utc(incident.last_at),
        "ackedBy": names.get(incident.acked_by),
        "ackedAt": iso_utc(incident.acked_at),
        "resolvedBy": names.get(incident.resolved_by),
        "resolvedAt": iso_utc(incident.resolved_at),
        "bundle": bundle,
        "servers": servers,
        "rules": json.loads(incident.rules) if incident.rules else None,
        "channels": ["bell", *(c for c in ("email", "telegram") if c in used)],
        "history": [
            {
                "id": e.id,
                "at": iso_utc(e.at),
                "kind": e.kind,
                "actor": names.get(e.actor_id),
                "text": e.text,
                "severity": e.severity,
                "serverId": e.server_id,
            }
            for e in entries
        ],
        "canAct": held.can_act,
        "row": feed_rows(db, user, [held.row], now)[0],
    }


def unread_count(db: Session, user: User, now: datetime) -> int:
    """The badge: unread rows that are neither hidden nor muted (the feed's muted)."""
    server_muted = (
        select(NotificationServerMute.server_id)
        .where(
            NotificationServerMute.user_id == Notification.user_id,
            NotificationServerMute.server_id == Notification.source_id,
            NotificationServerMute.until > now,
            Notification.source_type == "server",
        )
        .exists()
    )
    return (
        db.query(func.count(Notification.id))
        .filter(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
            Notification.hidden_at.is_(None),
            or_(
                Notification.incident_id.is_(None),
                and_(
                    or_(Notification.muted_until.is_(None), Notification.muted_until <= now),
                    ~server_muted,
                ),
            ),
        )
        .scalar()
    )


def server_mutes(db: Session, user: User, now: datetime) -> list[NotificationServerMute]:
    return (
        db.query(NotificationServerMute)
        .filter(NotificationServerMute.user_id == user.id, NotificationServerMute.until > now)
        .order_by(NotificationServerMute.server_id)
        .all()
    )


def may_mute_server(db: Session, user: User, server_id: str) -> bool:
    """A server the user sees: assigned, or any existing one for an admin."""
    if user.is_admin:
        return db.get(Server, server_id) is not None
    return server_id in _assigned(user)


def _assigned(user: User) -> set[str]:
    return set() if user.is_admin else {s.id for s in user.servers}


def _incident_servers(incident: NotificationIncident, members: list[str]) -> list[str]:
    """The servers an incident is about: a bundle's members, the server of a server
    incident; none for a notice of the server itself."""
    if members:
        return list(dict.fromkeys(members))
    if incident.source_type == "server" and incident.source_id:
        return [incident.source_id]
    return []


def _sight(user: User, assigned: set[str], servers: list[str]) -> tuple[set[str], bool] | None:
    """(the servers the user sees, whether that is every one), None when they see
    none. An incident without a server is the admins' (service._user_can_see)."""
    if user.is_admin:
        return set(servers), True
    visible = set(servers) & assigned
    if not visible:
        return None
    return visible, visible == set(servers)


def _mute(row: Notification, mutes: dict[str, datetime], now: datetime) -> dict:
    """A mute holds only a row of an incident: plain rows are never pinged again. A
    server mute only a row of a single server, as in _single_server."""
    if row.incident_id is not None:
        if row.muted_until is not None and row.muted_until > now:
            return {"muted": True, "mutedUntil": iso_utc(row.muted_until), "muteSource": "incident"}
        until = mutes.get(row.source_id) if row.source_type == "server" else None
        if until is not None:
            return {"muted": True, "mutedUntil": iso_utc(until), "muteSource": "server"}
    return {"muted": False, "mutedUntil": None, "muteSource": None}


def _usernames(db: Session, ids: Iterable[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return dict(db.query(User.id, User.username).filter(User.id.in_(wanted)).all())
