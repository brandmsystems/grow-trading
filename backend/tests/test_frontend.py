"""The built React app is served under /app with a client-side routing fallback."""
import app.main as app_module
from app.api import frontend


def test_serves_react_build_and_falls_back_to_index(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(frontend, "DIST", tmp_path)
    c = app_module.app.test_client()
    assert b"id=root" in c.get("/app/").data
    assert c.get("/app/assets/app.js").data == b"console.log(1)"
    assert b"id=root" in c.get("/app/some/client/route").data          # client-side route
    (tmp_path.parent / "secret.txt").write_text("API_KEY=nope", encoding="utf-8")
    for path in ("/app/../secret.txt", "/app/%2e%2e/secret.txt", "/app/..%2fsecret.txt"):
        assert b"API_KEY" not in c.get(path).data                       # nothing outside dist is served


def test_missing_build_explains_how_to_build(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend, "DIST", tmp_path / "nothing")
    r = app_module.app.test_client().get("/app/")
    assert r.status_code == 404 and b"npm run build" in r.data


def test_old_addresses_redirect_to_the_react_app():
    """There is one interface: old page URLs and the root go to the matching React page."""
    from app.api.pages import REDIRECTS
    c = app_module.app.test_client()
    for old, new in REDIRECTS.items():
        r = c.get(old)
        assert r.status_code == 302 and r.headers["Location"].endswith(new), old
    assert c.get("/static/app.css").status_code == 404          # old page assets are gone
