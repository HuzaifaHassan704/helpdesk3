import pytest
from pydantic import ValidationError

from app.core.config import Settings

GOOD_KEY = "k" * 40


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """conftest.py sets test env vars; these tests need Settings() to start from the real defaults."""
    for name in ("ENVIRONMENT", "SECRET_KEY", "CORS_ORIGINS", "ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_production_requires_strong_secret():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make(ENVIRONMENT="production")  # default dev key
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make(ENVIRONMENT="production", SECRET_KEY="too-short")
    assert make(ENVIRONMENT="production", SECRET_KEY=GOOD_KEY).ENVIRONMENT == "production"


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make(ENVIRONMENT="production", SECRET_KEY=GOOD_KEY, CORS_ORIGINS="https://a.example.com,*")


def test_development_allows_defaults():
    s = make(ENVIRONMENT="development")
    assert s.cors_origins_list == [] and s.allowed_hosts_list == ["*"]


def test_list_parsing():
    s = make(
        CORS_ORIGINS=" https://a.example.com/ , https://b.example.com ", ALLOWED_HOSTS="api.example.com, localhost"
    )
    assert s.cors_origins_list == ["https://a.example.com", "https://b.example.com"]
    assert s.allowed_hosts_list == ["api.example.com", "localhost"]
