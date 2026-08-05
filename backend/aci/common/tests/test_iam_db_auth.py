"""Unit tests for AWS RDS/Aurora IAM database authentication in aci.common.utils.

Pure-logic tests: boto3 is mocked and no real DB/AWS is contacted. The do_connect
hook is exercised against a real (but never-actually-connected) SQLAlchemy engine.
"""
from collections.abc import Iterator
from unittest import mock

import pytest
from sqlalchemy import create_engine, event

from aci.common import utils


@pytest.fixture(autouse=True)
def _reset_iam_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts and ends with a clean frozen flag and URL cache, since
    _iam_auth_enabled() is @cache'd and _db_url_cache is a module global."""
    utils._iam_auth_enabled.cache_clear()
    utils._db_url_cache = None
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
    monkeypatch.delenv("SERVER_DB_SSLMODE", raising=False)
    monkeypatch.delenv("SERVER_DB_SSLROOTCERT", raising=False)
    yield
    utils._iam_auth_enabled.cache_clear()
    utils._db_url_cache = None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        (" TRUE ", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("nope", False),
    ],
)
def test_iam_auth_flag_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("SERVER_DB_IAM_AUTH", value)
    utils._iam_auth_enabled.cache_clear()
    assert utils._iam_auth_enabled() is expected


def test_iam_auth_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVER_DB_IAM_AUTH", raising=False)
    utils._iam_auth_enabled.cache_clear()
    assert utils._iam_auth_enabled() is False


def test_iam_auth_flag_is_frozen_after_first_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the flag must be read once and stay fixed for the process
    so URL construction, engine setup, and Alembic never disagree (which could
    leave a passwordless URL with no token hook)."""
    monkeypatch.setenv("SERVER_DB_IAM_AUTH", "false")
    utils._iam_auth_enabled.cache_clear()
    assert utils._iam_auth_enabled() is False

    # Env flips mid-process; the frozen value must NOT change.
    monkeypatch.setenv("SERVER_DB_IAM_AUTH", "true")
    assert utils._iam_auth_enabled() is False


def test_build_iam_url_is_passwordless() -> None:
    url = utils._build_iam_sqlalchemy_url(
        "postgresql+psycopg", "iam_user", "my-rds.aws.com", "5432", "appdb"
    )
    assert url == "postgresql+psycopg://iam_user@my-rds.aws.com:5432/appdb"
    assert ":@" not in url  # no empty password
    assert "None" not in url


def test_construct_db_url_sync_iam_skips_password_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under IAM auth, the Secrets Manager password fetch must not run."""
    monkeypatch.setenv("SERVER_DB_IAM_AUTH", "true")
    utils._iam_auth_enabled.cache_clear()

    def _boom() -> str:
        raise AssertionError("password fetch must not be called under IAM auth")

    monkeypatch.setattr(utils, "get_db_password_sync", _boom)

    url = utils.construct_db_url_sync(
        "postgresql+psycopg", "iam_user", "my-rds.aws.com", "5432", "appdb"
    )
    assert url == "postgresql+psycopg://iam_user@my-rds.aws.com:5432/appdb"


def _capture_do_connect_cparams(engine: object) -> dict:
    """Attach a do_connect listener that captures the final cparams and aborts
    before any real network connection is attempted."""
    captured: dict = {}

    @event.listens_for(engine, "do_connect")
    def _capture(dialect: object, conn_rec: object, cargs: list, cparams: dict) -> None:
        captured.update(cparams)
        raise _StopBeforeConnect

    return captured


class _StopBeforeConnect(Exception):
    pass


def test_do_connect_injects_fresh_token_and_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rds = mock.Mock()
    fake_rds.generate_db_auth_token.return_value = "FRESH_IAM_TOKEN"

    url = utils._build_iam_sqlalchemy_url(
        "postgresql+psycopg", "iam_user", "my-rds.aws.com", "5432", "appdb"
    )
    with mock.patch("boto3.client", return_value=fake_rds) as mk:
        engine = create_engine(url)
        utils.attach_iam_token_provider(engine)
        captured = _capture_do_connect_cparams(engine)
        with pytest.raises(Exception):
            engine.connect()

    assert captured["password"] == "FRESH_IAM_TOKEN"
    assert captured["sslmode"] == "require"
    assert "sslrootcert" not in captured
    mk.assert_called_once_with("rds", region_name="us-east-1")
    fake_rds.generate_db_auth_token.assert_called_once_with(
        DBHostname="my-rds.aws.com", Port=5432, DBUsername="iam_user", Region="us-east-1"
    )


def test_do_connect_sslmode_override_and_rootcert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVER_DB_SSLMODE", "verify-full")
    monkeypatch.setenv("SERVER_DB_SSLROOTCERT", "/certs/rds-ca.pem")
    fake_rds = mock.Mock()
    fake_rds.generate_db_auth_token.return_value = "TOK"

    url = utils._build_iam_sqlalchemy_url(
        "postgresql+psycopg", "iam_user", "my-rds.aws.com", "5432", "appdb"
    )
    with mock.patch("boto3.client", return_value=fake_rds):
        engine = create_engine(url)
        utils.attach_iam_token_provider(engine)
        captured = _capture_do_connect_cparams(engine)
        with pytest.raises(Exception):
            engine.connect()

    assert captured["sslmode"] == "verify-full"
    assert captured["sslrootcert"] == "/certs/rds-ca.pem"
