"""Web backend tests (mock provider, no network). Skipped if FastAPI absent."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_APP_PASSWORD", "secret")
    monkeypatch.setenv("WEB_APP_SECRET", "unit-secret")
    monkeypatch.chdir(tmp_path)  # outputs/ lands in the temp dir
    from web.server import create_app

    with TestClient(create_app()) as c:
        yield c


def _login(client) -> dict:
    r = client.post("/api/login", json={"password": "secret"})
    assert r.status_code == 200
    return {"authorization": f"Bearer {r.json()['token']}"}


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_health_and_auth_gate(client):
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/config").status_code == 401  # no token
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401


def test_config_lists_providers_and_master_prompt(client):
    h = _login(client)
    cfg = client.get("/api/config", headers=h).json()
    names = {p["name"] for p in cfg["providers"]}
    assert {"openai", "fal", "mock"} <= names
    assert "CONSISTENCY" in cfg["default_master_prompt"].upper()


def test_run_streams_images_with_mock(client):
    h = _login(client)
    config = {
        "name": "t",
        "master_prompt": "KEEP PRODUCT IDENTICAL",
        "agents": [
            {"provider": "mock", "model": "mock-v1", "prompt": "studio", "images": 2},
            {"provider": "mock", "model": "mock-v1", "prompt": "outdoor", "images": 1},
        ],
    }
    r = client.post(
        "/api/run",
        headers=h,
        data={"config": json.dumps(config)},
        files=[("references", ("p.png", _png_bytes(), "image/png"))],
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert r.json()["total"] == 3

    token = h["authorization"].split()[1]
    events, images = [], 0
    with client.stream("GET", f"/api/run/{run_id}/events?token={token}") as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                events.append(ev["type"])
                if ev["type"] == "image":
                    images += len(ev["images"])
                    # fetch the served image
                    fname = ev["images"][0]["file"]
                    img = client.get(f"/api/run/{run_id}/image/{fname}?token={token}")
                    assert img.status_code == 200 and len(img.content) > 0
                if ev["type"] == "done":
                    assert ev["succeeded"] == 3
                    break
    assert images == 3
    # Progress contract: a task is first "queued" (accepted, maybe waiting on a
    # provider limit), then "running" (real API call started), then "image".
    assert "queued" in events and "running" in events
    assert "image" in events and "done" in events


def test_run_requires_reference(client):
    h = _login(client)
    config = {"agents": [{"provider": "mock", "prompt": "x"}]}
    r = client.post("/api/run", headers=h, data={"config": json.dumps(config)})
    assert r.status_code == 400


def test_image_path_traversal_blocked(client):
    h = _login(client)
    token = h["authorization"].split()[1]
    config = {"agents": [{"provider": "mock", "model": "mock-v1", "prompt": "x", "images": 1}]}
    r = client.post(
        "/api/run", headers=h, data={"config": json.dumps(config)},
        files=[("references", ("p.png", _png_bytes(), "image/png"))],
    )
    run_id = r.json()["run_id"]
    # attempt traversal — must not escape images/
    bad = client.get(f"/api/run/{run_id}/image/..%2f..%2fmetadata.jsonl?token={token}")
    assert bad.status_code == 404


def test_workspaces_save_list_get_delete(client):
    h = _login(client)
    token = h["authorization"].split()[1]
    cfg = {"name": "My Project", "master_prompt": "KEEP IT", "agents": [
        {"provider": "mock", "model": "mock-v1", "prompt": "studio", "images": 20},
    ]}
    r = client.post(
        "/api/workspaces", headers=h,
        data={"config": json.dumps(cfg)},
        files=[("references", ("p.png", _png_bytes(), "image/png"))],
    )
    assert r.status_code == 200
    wid = r.json()["id"]

    lst = client.get("/api/workspaces", headers=h).json()["workspaces"]
    assert any(w["id"] == wid and w["name"] == "My Project" and w["refs"] == 1 for w in lst)

    got = client.get(f"/api/workspaces/{wid}", headers=h).json()
    assert got["master_prompt"] == "KEEP IT" and len(got["agents"]) == 1
    assert len(got["refs"]) == 1

    img = client.get(f"/api/workspaces/{wid}/ref/{got['refs'][0]}?token={token}")
    assert img.status_code == 200 and len(img.content) > 0

    # auth gate + traversal safety
    assert client.get(f"/api/workspaces/{wid}").status_code == 401
    assert client.get(f"/api/workspaces/{wid}/ref/..%2f..%2fworkspace.json?token={token}").status_code == 404

    assert client.delete(f"/api/workspaces/{wid}", headers=h).json()["deleted"] is True
    assert client.get(f"/api/workspaces/{wid}", headers=h).status_code == 404
