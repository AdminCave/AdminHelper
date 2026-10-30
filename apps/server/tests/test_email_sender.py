# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""send_email TLS (6.149, smtp-hardening T3), the same as the monitoring alerter's e-mail path:
port 465 = implicit TLS (SMTP_SSL from the start), every other port (25, 2525, 587, ...) upgrades via
STARTTLS BEFORE login(), and both use a verifying context (certificate + hostname). A failing STARTTLS
(no TLS offered, untrusted certificate) raises before login() and the send; the outbox retries it.
This is the clear-text-login guard the code comment relies on — a regression (STARTTLS moved after
login, dropped for a port, or run without a verifying context) would silently push the SMTP
credentials over an unencrypted or unauthenticated channel, and the outbox tests stub send_email out
entirely.

SMTP_CA_FILE (smtp-hardening T5) adds a relay's private CA to that same context, on top of the system
CAs, so verification stays on; a missing or broken file raises before any connection is opened."""

import datetime
import smtplib
import ssl
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import app.modules.notifications.sender as sender


def _configure(monkeypatch, port):
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", port)
    monkeypatch.setattr(sender, "SMTP_FROM", "from@example.com")
    monkeypatch.setattr(sender, "SMTP_USER", "u")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(sender, "SMTP_CA_FILE", "")


def _assert_verifying(ctx):
    # The guard is the context, not just the call: starttls() or SMTP_SSL without one
    # wrap the socket without checking certificate or hostname, so a MITM passes.
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_port_465_uses_implicit_tls_and_no_starttls(monkeypatch):
    _configure(monkeypatch, 465)
    ssl_mock = MagicMock()
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)

    sender.send_email("to@example.com", "subj", "body")

    ssl_mock.assert_called_once()  # implicit TLS from the start
    _assert_verifying(ssl_mock.call_args.kwargs.get("context"))
    plain_mock.assert_not_called()  # plain SMTP must not be used on 465
    server = ssl_mock.return_value.__enter__.return_value
    server.starttls.assert_not_called()  # channel already encrypted
    server.login.assert_called_once_with("u", "p")
    server.send_message.assert_called_once()


def test_port_587_runs_starttls_before_login(monkeypatch):
    _configure(monkeypatch, 587)
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)

    sender.send_email("to@example.com", "subj", "body")

    plain_mock.assert_called_once()
    ssl_mock.assert_not_called()  # 587 uses plain SMTP + STARTTLS, not SMTPS
    server = plain_mock.return_value.__enter__.return_value
    # STARTTLS must run BEFORE login() so the credentials never cross the wire in clear text.
    methods = [c[0] for c in server.method_calls]
    assert "starttls" in methods
    assert methods.index("starttls") < methods.index("login")
    server.send_message.assert_called_once()


@pytest.mark.parametrize("port", [25, 2525, 587])
def test_every_port_but_465_runs_verifying_starttls_before_login(monkeypatch, port):
    _configure(monkeypatch, port)
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)

    sender.send_email("to@example.com", "subj", "body")

    plain_mock.assert_called_once()
    ssl_mock.assert_not_called()
    server = plain_mock.return_value.__enter__.return_value
    methods = [c[0] for c in server.method_calls]
    assert "starttls" in methods
    assert methods.index("starttls") < methods.index("login")
    _assert_verifying(server.starttls.call_args.kwargs.get("context"))
    server.send_message.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server."),
        ssl.SSLCertVerificationError("certificate verify failed"),
    ],
    ids=["no-starttls", "untrusted-certificate"],
)
def test_failed_starttls_raises_before_login_and_send(monkeypatch, error):
    _configure(monkeypatch, 25)
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", MagicMock())
    server = plain_mock.return_value.__enter__.return_value
    server.starttls.side_effect = error

    with pytest.raises(type(error)):
        sender.send_email("to@example.com", "subj", "body")

    server.starttls.assert_called_once()
    server.login.assert_not_called()  # the credentials never cross a channel without TLS
    server.send_message.assert_not_called()


_CA_CN = "smtp-hardening test relay CA"


def _write_ca_pem(path) -> str:
    """A self-signed CA as PEM, standing in for a relay's company or private CA."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CA_CN)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


def _ca_common_names(ctx) -> list[str]:
    return [
        value
        for cert in ctx.get_ca_certs()
        for rdn in cert["subject"]
        for key, value in rdn
        if key == "commonName"
    ]


def _sent_context(monkeypatch, port):
    """The TLS context send_email hands to SMTP_SSL (465) or to starttls() (any other port)."""
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)
    sender.send_email("to@example.com", "subj", "body")
    if port == 465:
        plain_mock.assert_not_called()
        ssl_mock.return_value.__enter__.return_value.send_message.assert_called_once()
        return ssl_mock.call_args.kwargs.get("context")
    ssl_mock.assert_not_called()
    server = plain_mock.return_value.__enter__.return_value
    server.send_message.assert_called_once()
    return server.starttls.call_args.kwargs.get("context")


def _spy_default_context(monkeypatch) -> list:
    """Every context ssl.create_default_context hands out while the test runs."""
    created = []
    real_create = sender.ssl.create_default_context

    def spy(*args, **kwargs):
        created.append(real_create(*args, **kwargs))
        return created[-1]

    monkeypatch.setattr(sender.ssl, "create_default_context", spy)
    return created


@pytest.mark.parametrize("port", [587, 465])
def test_smtp_ca_file_adds_the_relay_ca_to_the_verifying_context(monkeypatch, tmp_path, port):
    _configure(monkeypatch, port)
    monkeypatch.setattr(sender, "SMTP_CA_FILE", _write_ca_pem(tmp_path / "smtp-ca.pem"))
    created = _spy_default_context(monkeypatch)

    ctx = _sent_context(monkeypatch, port)

    # The default context with the file added, not one built from the file alone: the count
    # below cannot tell the two apart on a box whose system CAs sit in a lazily read directory.
    assert created == [ctx]
    assert _CA_CN in _ca_common_names(ctx)
    # On top of the system CAs, not instead of them: a context built from the file alone
    # would reject every public relay. Holds on a box without a CA bundle too (0 + 1).
    system_cas = ssl.create_default_context().cert_store_stats()["x509_ca"]
    assert ctx.cert_store_stats()["x509_ca"] == system_cas + 1
    _assert_verifying(ctx)  # an extra CA, not a weaker check


@pytest.mark.parametrize("port", [587, 465])
def test_without_smtp_ca_file_the_context_has_no_extra_ca(monkeypatch, tmp_path, port):
    # Pairs with the test above: the CA in the file is what put its name there.
    _write_ca_pem(tmp_path / "smtp-ca.pem")
    _configure(monkeypatch, port)
    created = _spy_default_context(monkeypatch)

    ctx = _sent_context(monkeypatch, port)

    assert _CA_CN not in _ca_common_names(ctx)
    _assert_verifying(ctx)
    # Whether a box loads its system CAs eagerly or from a hashed directory, the context has to
    # be the default one; one built from nothing passes the CA-name check on a lazy box.
    assert created == [ctx]


@pytest.mark.parametrize(
    ("content", "error"),
    [(None, "FileNotFoundError"), ("not a certificate\n", "SSLError")],
    ids=["missing", "not-pem"],
)
def test_unloadable_smtp_ca_file_raises_before_connecting(monkeypatch, tmp_path, content, error):
    ca_file = tmp_path / "smtp-ca.pem"
    if content is not None:
        ca_file.write_text(content)
    _configure(monkeypatch, 587)
    monkeypatch.setattr(sender, "SMTP_CA_FILE", str(ca_file))
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)

    with pytest.raises(RuntimeError) as raised:
        sender.send_email("to@example.com", "subj", "body")

    # The outbox stores only str(exc): the variable, the path, the kind and the reason must be in it.
    assert str(raised.value) == (
        f"SMTP_CA_FILE {ca_file} cannot be loaded: {error}: {raised.value.__cause__}"
    )
    plain_mock.assert_not_called()  # no connection, so nothing for the relay to see
    ssl_mock.assert_not_called()


def test_subject_is_one_line_like_the_monitoring_alerter(monkeypatch):
    # Same rule as apps/monitoring/app/alerter.py _SUBJECT_TO_SPACE: control characters, DEL,
    # C1 and the line and paragraph separators become a space, one for one; the body stays.
    _configure(monkeypatch, 587)
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)

    sender.send_email("to@example.com", "a\r\nb\x85c\u2028d\x7fe\tf\u2029g", "line 1\nline 2")

    message = plain_mock.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert message["Subject"] == "a  b c d e f g"
    assert message.get_payload()[0].get_payload() == "line 1\nline 2"
    message.as_string()  # a CR or LF left in the header would raise here
