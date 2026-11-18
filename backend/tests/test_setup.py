import pytest
from app.config import settings as config
import app.main as app_module


def _write(tmp_path, text):
    p = tmp_path / "keys.txt"
    p.write_text(text)
    return p


@pytest.mark.parametrize("text", [
    "API_KEY=abc\nTOTP_SECRET=JBSW Y3DP\n",
    "api key: abc\ntotp secret: JBSWY3DP\n",
    "# comment\nabc\nJBSWY3DP\n",
    "TOTP_SECRET='JBSWY3DP'\nGROWW_API_KEY=\"abc\"\n",
])
def test_load_keys_formats(tmp_path, text):
    assert config.load_keys(_write(tmp_path, text)) == ("abc", "JBSWY3DP")


def test_load_keys_missing(tmp_path):
    with pytest.raises(config.KeysError):
        config.load_keys(tmp_path / "nope.txt")
    with pytest.raises(config.KeysError):
        config.load_keys(_write(tmp_path, "only-one-line\n"))
    with pytest.raises(config.KeysError):
        config.load_keys(_write(tmp_path, "API_KEY=abc\nTOTP_SECRET=\n"))


def test_routes_without_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "KEYS_FILE", tmp_path / "keys.txt")
    monkeypatch.setattr(config, "TOKEN_CACHE", tmp_path / "tok.json")
    monkeypatch.setattr(config.load_keys, "__defaults__", (tmp_path / "keys.txt",))
    c = app_module.app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/app/")
    assert c.get("/api/status").json["keys"] is False
    r = c.post("/api/login")
    assert r.status_code == 400 and r.json["kind"] == "keys"


@pytest.mark.parametrize("text", [
    "API_KEY=abc\nAPI_SECRET=a)#b-c^$d\nTOTP_SECRET=\n",
    "API_KEY=abc\nTOTP_SECRET=\nAPI_SECRET=a)#b-c^$d\n",
])
def test_load_keys_api_secret_survives_empty_totp(tmp_path, text):
    assert config.load_keys(_write(tmp_path, text)) == ("abc", "a)#b-c^$d")


def test_env_credentials_take_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("GROWW_API_KEY", "envkey")
    monkeypatch.setenv("GROWW_TOTP_SECRET", "JBSW Y3DP")
    assert config.load_keys() == ("envkey", "JBSWY3DP")
    monkeypatch.delenv("GROWW_TOTP_SECRET")
    with pytest.raises(config.KeysError):
        config.load_keys()
    monkeypatch.delenv("GROWW_API_KEY")
    assert config.load_keys(_write(tmp_path, "API_KEY=abc" + chr(10) + "TOTP_SECRET=JBSWY3DP" + chr(10))) == ("abc", "JBSWY3DP")
