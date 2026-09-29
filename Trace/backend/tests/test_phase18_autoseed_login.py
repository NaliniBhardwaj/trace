"""Phase 18 hotfix regression test.

Reproduces exactly the bug found in SENTINEL_PHASE17_HOTFIX_LOGIN_MAP: a
freshly-unzipped/empty SQLite dev DB left demo accounts unseeded, so
POST /auth/login returned 401 for worker@sentinel.demo until someone
manually ran `python -m app.seed`.

This must run in a genuinely fresh Python subprocess (not just a fresh
sqlite file) because `app.main`'s top-level auto-seed code — like the rest
of this test suite's app-under-test — only executes on first import per
process, and every other test module in this suite has already imported
app.main by the time pytest collects this file.
"""
import os
import subprocess
import sys
import textwrap


def test_fresh_empty_db_autoseeds_and_login_works(tmp_path):
    db_path = tmp_path / "phase18_autoseed_test.db"
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    script = textwrap.dedent(f"""
        import os, sys
        os.environ["DATABASE_URL"] = "sqlite:///{db_path}"
        os.environ["ML_ENABLED"] = "false"
        sys.path.insert(0, {backend_dir!r})

        from fastapi.testclient import TestClient
        from app.main import app  # top-level code must auto-seed the empty DB here

        client = TestClient(app)
        r = client.post("/auth/login", json={{"email": "worker@sentinel.demo", "password": "Password123!"}})
        assert r.status_code == 200, f"login failed on a fresh DB: {{r.status_code}} {{r.text}}"
        assert "access_token" in r.json()
        print("OK")
    """)

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=backend_dir,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "OK" in result.stdout
    assert db_path.exists()
