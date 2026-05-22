"""Notification channels — Pushover, email, generic webhook."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scanner import channels


def test_pushover_skipped_without_credentials():
    with patch("requests.post") as post:
        channels.send_pushover({}, "t", "b", "u")
        post.assert_not_called()


def test_pushover_posts_with_creds():
    with patch("requests.post") as post:
        channels.send_pushover(
            {"user_key": "u", "app_token": "t", "priority": 1, "sound": "siren"},
            "title", "body", "https://x",
        )
        post.assert_called_once()
        called_data = post.call_args.kwargs["data"]
        assert called_data["user"] == "u"
        assert called_data["token"] == "t"
        assert called_data["priority"] == "1"


def test_pushover_swallows_request_exception():
    import requests
    with patch("requests.post", side_effect=requests.ConnectionError("nope")):
        # Must not raise.
        channels.send_pushover({"user_key": "u", "app_token": "t"}, "t", "b")


def test_email_skipped_without_host():
    with patch("smtplib.SMTP") as smtp:
        channels.send_email({}, "subj", "body")
        smtp.assert_not_called()


def test_email_skipped_without_to():
    with patch("smtplib.SMTP") as smtp:
        channels.send_email(
            {"smtp_host": "x", "from": "a@b.c", "to": []},
            "subj", "body",
        )
        smtp.assert_not_called()


def test_email_sends_with_starttls_and_login():
    fake_smtp = MagicMock()
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = fake_smtp
        channels.send_email(
            {
                "smtp_host": "smtp.example",
                "smtp_port": 587,
                "smtp_starttls": True,
                "smtp_user": "u",
                "smtp_password": "p",
                "from": "from@x",
                "to": ["a@b", "c@d"],
            },
            "subj", "body",
        )
        fake_smtp.starttls.assert_called_once()
        fake_smtp.login.assert_called_once_with("u", "p")
        fake_smtp.sendmail.assert_called_once()


def test_email_accepts_comma_separated_to():
    fake_smtp = MagicMock()
    with patch("smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = fake_smtp
        channels.send_email(
            {"smtp_host": "x", "from": "f@x", "to": "a@b, c@d"},
            "s", "b",
        )
        args = fake_smtp.sendmail.call_args.args
        assert args[1] == ["a@b", "c@d"]


def test_generic_webhook_posts_json_body():
    with patch("requests.post") as post:
        channels.send_generic_webhook("https://hook.x", {"a": 1, "b": "x"})
        post.assert_called_once()
        data = json.loads(post.call_args.kwargs["data"])
        assert data == {"a": 1, "b": "x"}


def test_generic_webhook_skipped_when_url_empty():
    with patch("requests.post") as post:
        channels.send_generic_webhook("", {"a": 1})
        post.assert_not_called()
