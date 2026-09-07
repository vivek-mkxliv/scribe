"""Integration tests for the local GUI HTTP server (`gui/server.py`).

Spins up a real server on `127.0.0.1:0` (OS-assigned free port) in a background thread and makes
real HTTP requests via `urllib.request` -- no mocking of `http.server` internals, no external
network, deterministic and fast. `pipeline.run` itself is monkeypatched so no real LLM call ever
happens here.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from scribe.gui import server as server_module


def _fake_resolution(*_args, **_kwargs):
    from scribe.providers.resolution import ProviderResolution

    return ProviderResolution(provider="ollama", api_key=None)


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    server = server_module.build_server(tmp_path, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, json.loads(resp.read())


def _post(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _delete(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


def test_root_serves_html(running_server):
    base_url, _ = running_server
    with urllib.request.urlopen(base_url + "/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        assert b"<html" in resp.read()


def test_unknown_path_returns_404(running_server):
    base_url, _ = running_server
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(base_url + "/nope")
    assert exc_info.value.code == 404


def test_form_defaults_endpoint(running_server):
    base_url, _ = running_server
    status, payload = _get(base_url + "/api/form-defaults")
    assert status == 200
    assert payload["mode"] == "lean_technical"


def test_presets_round_trip_via_http(running_server):
    base_url, repo_path = running_server

    save_status, save_payload = _post(base_url + "/api/presets/quick-draft", {"mode": "operator_split"})
    assert save_status == 200
    assert save_payload == {"saved": "quick-draft"}

    list_status, list_payload = _get(base_url + "/api/presets")
    assert list_status == 200
    assert list_payload == {"presets": {"quick-draft": {"mode": "operator_split"}}}

    delete_status, delete_payload = _delete(base_url + "/api/presets/quick-draft")
    assert delete_status == 200
    assert delete_payload == {"deleted": True}
    assert not (repo_path / "scribe.presets.json").exists()


def test_saving_a_preset_with_a_raw_api_key_is_rejected_via_http(running_server):
    base_url, _ = running_server
    status, payload = _post(base_url + "/api/presets/bad", {"api_key": "sk-should-not-be-saved"})
    assert status == 400
    assert "api_key" in payload["error"]


def test_generate_and_status_polling_reports_completion(running_server, monkeypatch):
    base_url, repo_path = running_server
    written_path = repo_path / "docs" / "README.md"
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", _fake_resolution)
    monkeypatch.setattr("scribe.gui.app.pipeline.run", lambda config, on_status: [written_path])

    status, payload = _post(base_url + "/api/generate", {"form": {"model": "llama3.1:8b"}, "confirmed": True})
    assert status == 200
    assert payload == {"started": True}

    deadline = time.time() + 2
    final_state = None
    while time.time() < deadline:
        _, state = _get(base_url + "/api/status")
        if not state["running"]:
            final_state = state
            break
        time.sleep(0.02)

    assert final_state is not None, "generation never finished"
    assert final_state["written"] == [str(written_path)]
    assert final_state["error"] is None


def test_generate_rejects_a_second_concurrent_run(running_server, monkeypatch):
    base_url, _ = running_server

    def _slow_run(config, on_status):
        time.sleep(0.3)
        return []

    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", _fake_resolution)
    monkeypatch.setattr("scribe.gui.app.pipeline.run", _slow_run)

    first_status, _ = _post(base_url + "/api/generate", {"form": {"model": "llama3.1:8b"}, "confirmed": True})
    assert first_status == 200
    second_status, second_payload = _post(
        base_url + "/api/generate", {"form": {"model": "llama3.1:8b"}, "confirmed": True}
    )
    assert second_status == 409
    assert "already in progress" in second_payload["error"]

    # Wait for the first (slow) run's background thread to actually finish before this test
    # returns -- `monkeypatch.setattr("scribe.gui.app.pipeline.run", ...)` patches the real,
    # shared `scribe.pipeline` module object (since `gui/app.py` does `from scribe import
    # pipeline`), not a private copy. A daemon thread left running past this test's own scope
    # would resolve `pipeline.run` dynamically at call time and could pick up whatever another
    # test has since monkeypatched it to -- a real cross-test contamination hazard, not just a
    # leaked thread. Every test here must ensure its background generation thread is done
    # before returning, the same way `test_generate_and_status_polling_reports_completion` does.
    deadline = time.time() + 2
    while time.time() < deadline:
        _, state = _get(base_url + "/api/status")
        if not state["running"]:
            break
        time.sleep(0.02)
    else:
        pytest.fail("first (slow) run never finished")
