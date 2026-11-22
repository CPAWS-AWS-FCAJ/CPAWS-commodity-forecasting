"""secret_store.get_eia_api_key(): EIA_API_KEY → SSM Parameter Store (EIA_SECRET_ID) → lỗi.

Dùng client SSM giả; không gọi AWS thật (boto3.client bị chặn trong mọi test của file này).
"""

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from src.data import ingest_prices, secret_store

PARAM = "/cpaws/dev/eia-api-key"
SECRET = "eia-test-value-7f3a"  # giá trị giả, kiểm tra không lọt vào message/log


class FakeSSM:
    """Ghi lại các lời gọi get_parameter; trả value hoặc raise error."""

    def __init__(self, value=SECRET, error=None):
        self.value = value
        self.error = error
        self.calls: list[dict] = []

    def get_parameter(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"Parameter": {"Name": kwargs["Name"], "Type": "SecureString", "Value": self.value}}


def _client_error(code: str) -> ClientError:
    msg = f"{code} for {PARAM}"
    return ClientError({"Error": {"Code": code, "Message": msg}}, "GetParameter")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for k in ("EIA_API_KEY", "EIA_SECRET_ID"):
        monkeypatch.delenv(k, raising=False)

    def no_real_client(*a, **k):
        raise AssertionError("test must not create a real boto3 client")

    monkeypatch.setattr(boto3, "client", no_real_client)
    secret_store._clear_cache()
    yield
    secret_store._clear_cache()


def test_env_key_wins_without_calling_ssm(monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", " local-key ")
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM()
    assert secret_store.get_eia_api_key(client=client) == "local-key"
    assert client.calls == []


def test_secret_id_reads_ssm_with_decryption(monkeypatch):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM(value=f"  {SECRET}\n")
    assert secret_store.get_eia_api_key(client=client) == SECRET
    assert client.calls == [{"Name": PARAM, "WithDecryption": True}]


def test_ssm_value_cached_per_process(monkeypatch):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM()
    assert secret_store.get_eia_api_key(client=client) == SECRET
    assert secret_store.get_eia_api_key(client=client) == SECRET
    assert len(client.calls) == 1
    secret_store._clear_cache()
    secret_store.get_eia_api_key(client=client)
    assert len(client.calls) == 2


@pytest.mark.parametrize("code", ["ParameterNotFound", "AccessDeniedException"])
def test_client_error_becomes_secret_unavailable(monkeypatch, code):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM(error=_client_error(code))
    with pytest.raises(secret_store.SecretUnavailable) as ei:
        secret_store.get_eia_api_key(client=client)
    msg = str(ei.value)
    assert PARAM in msg and code in msg and SECRET not in msg
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    # lỗi không được cache: lần sau gọi lại SSM
    with pytest.raises(secret_store.SecretUnavailable):
        secret_store.get_eia_api_key(client=client)
    assert len(client.calls) == 2


def test_botocore_error_becomes_secret_unavailable(monkeypatch):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    with pytest.raises(secret_store.SecretUnavailable, match="NoCredentialsError"):
        secret_store.get_eia_api_key(client=FakeSSM(error=NoCredentialsError()))


@pytest.mark.parametrize("value", ["", "   \n"])
def test_empty_value_becomes_secret_unavailable(monkeypatch, value):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    with pytest.raises(secret_store.SecretUnavailable, match="empty"):
        secret_store.get_eia_api_key(client=FakeSSM(value=value))


def test_no_configuration_raises():
    with pytest.raises(secret_store.SecretUnavailable, match="not set"):
        secret_store.get_eia_api_key(client=FakeSSM())


def test_default_client_is_ssm(monkeypatch):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM()
    created = []
    monkeypatch.setattr(boto3, "client", lambda svc, **k: created.append(svc) or client)
    assert secret_store.get_eia_api_key() == SECRET
    assert created == ["ssm"]


def test_ingest_skips_eia_when_ssm_fails(monkeypatch, caplog):
    monkeypatch.setenv("EIA_SECRET_ID", PARAM)
    client = FakeSSM(error=_client_error("AccessDeniedException"))
    monkeypatch.setattr(boto3, "client", lambda svc, **k: client)
    with caplog.at_level("WARNING", logger="cpaws.ingest"):
        sources, _ = ingest_prices.build_sources()
    assert "eia" not in sources and "yfinance" in sources
    assert len(client.calls) == 1
    text = caplog.text
    assert "INGEST_REFERENCE_FAILED source=eia" in text and "AccessDeniedException" in text
    assert SECRET not in text
