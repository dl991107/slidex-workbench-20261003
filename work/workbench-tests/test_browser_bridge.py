import copy
import importlib.util
import json
import threading
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PATH = ROOT / "outputs/Slidex工作台.app/Contents/Resources/browser_bridge.py"
ENDPOINT = "http://127.0.0.1:9222"
FULL_URL = "https://example.invalid/test?private=secret"
WS = "ws://127.0.0.1:9222/devtools/browser/abc"


def _load_backend():
    assert BRIDGE_PATH.is_file(), "browser_bridge has not been implemented"
    spec = importlib.util.spec_from_file_location("slidex_workbench_browser_bridge", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def backend():
    return _load_backend()


def _snapshot(websocket=WS, target_id="tab-a", target_url=FULL_URL, targets=None):
    targets = targets or [{"id": target_id, "title": "Title", "url": target_url}]
    return {"websocket": websocket, "targets": copy.deepcopy(targets)}


def _result(status="passed", provider="geetest", elapsed_ms=7):
    return {"status": status, "provider": provider, "elapsed_ms": elapsed_ms,
            "private_debug": "PRIVATE_RUNNER_SECRET"}


def _bridge(backend, snapshot=None, runner=None):
    calls = []
    state = {"snapshot": snapshot or _snapshot()}

    def discover(endpoint):
        calls.append(endpoint)
        return copy.deepcopy(state["snapshot"])

    bridge = backend.BrowserBridge(discover=discover, runner=runner or (lambda record, event: _result()))
    return bridge, calls, state


def _assert_error(exc, statuses=(400,)):
    assert exc.value.status in statuses
    assert isinstance(exc.value.code, str) and isinstance(exc.value.message, str)


@pytest.mark.parametrize("value", [None, {}, "", "http://127.0.0.1", "http://127.0.0.1:0",
                                    "http://127.0.0.1:65536", "https://127.0.0.1:9222",
                                    "http://192.168.1.2:9222", "http://127.0.0.1:9222/path",
                                    "http://127.0.0.1:9222?x=1", "http://user@127.0.0.1:9222"])
def test_normalize_endpoint_rejects_unsafe_values(backend, value):
    with pytest.raises(backend.BridgeError) as exc:
        backend.normalize_endpoint(value)
    _assert_error(exc)


def test_normalize_endpoint_canonicalizes_localhost(backend):
    assert backend.normalize_endpoint("http://localhost:9222/") == ENDPOINT
    assert backend.normalize_endpoint(ENDPOINT) == ENDPOINT


@pytest.mark.parametrize("payload", [None, {}, {"endpoint": None}, {"endpoint": ENDPOINT, "extra": 1},
                                    {"endpoint": "http://127.0.0.1"}])
def test_connect_rejects_null_missing_or_unknown_fields(backend, payload):
    bridge, calls, _ = _bridge(backend)
    with pytest.raises(backend.BridgeError) as exc:
        bridge.connect(payload)
    _assert_error(exc)
    assert calls == []


def test_connect_is_only_discovery_side_effect_and_redacts_targets(backend):
    bridge, calls, _ = _bridge(backend)
    assert calls == []
    output = bridge.connect({"endpoint": "http://localhost:9222/"})
    assert calls == [ENDPOINT]
    assert output["ok"] is True and isinstance(output["message"], str)
    target = output["targets"][0]
    assert target["id"] != "tab-a" and target["url"] == "https://example.invalid"
    assert "private" not in json.dumps(output)


def test_run_rejects_invalid_target_and_does_not_call_runner(backend):
    calls = []
    bridge, _, _ = _bridge(backend, runner=lambda record, event: calls.append(record))
    bridge.connect({"endpoint": ENDPOINT})
    for payload in (None, {}, {"target": "bad", "request_id": str(uuid.uuid4())},
                    {"target": "bad", "request_id": "not-a-uuid"}):
        with pytest.raises(backend.BridgeError) as exc:
            bridge.run(payload)
        _assert_error(exc, (400, 404, 409, 410))
    assert calls == []


@pytest.mark.parametrize("change", ["websocket", "target_id", "target_url"])
def test_run_revalidates_browser_identity_target_and_full_url(backend, change):
    calls = []
    bridge, discover_calls, state = _bridge(backend, runner=lambda record, event: calls.append(record))
    handle = bridge.connect({"endpoint": ENDPOINT})["targets"][0]["id"]
    state["snapshot"] = _snapshot(
        websocket="ws://127.0.0.1:9222/devtools/browser/changed" if change == "websocket" else WS,
        target_id="tab-b" if change == "target_id" else "tab-a",
        target_url="https://example.invalid/changed" if change == "target_url" else FULL_URL,
    )
    with pytest.raises(backend.BridgeError) as exc:
        bridge.run({"target": handle, "request_id": str(uuid.uuid4())})
    _assert_error(exc, (409, 410))
    assert len(discover_calls) == 2 and calls == []


def test_run_uses_full_internal_record_and_whitelists_result(backend):
    records = []
    bridge, _, _ = _bridge(backend, runner=lambda record, event: (records.append(record) or _result()))
    handle = bridge.connect({"endpoint": ENDPOINT})["targets"][0]["id"]
    output = bridge.run({"target": handle, "request_id": str(uuid.uuid4())})
    assert set(output) == {"ok", "result"} and output["ok"] is True
    assert set(output["result"]) == {"status", "provider", "elapsed_ms", "message"}
    assert output["result"]["status"] == "passed"
    assert "PRIVATE_RUNNER_SECRET" not in json.dumps(output)
    assert records[0] == {"endpoint": ENDPOINT, "websocket": WS, "id": "tab-a", "url": FULL_URL}


@pytest.mark.parametrize('reason,expected',[
    ('no_provider','仅内置极验（GeeTest）和阿里云 NoCaptcha'),
    ('bounds_unavailable','按钮或轨道'),('images_unavailable','图片'),
    ('gap_uncertain','可信度'),('distance_invalid','拖动距离'),
    ('frame_unavailable','所属框架'),('page_changed','页面地址'),
    ('PRIVATE_UNKNOWN_REASON','未取得具体原因'),
    (None,'未取得具体原因'),([], '未取得具体原因'),
])
def test_unsupported_message_preserves_only_known_cause(backend,reason,expected):
    def runner(record,event):
        return {'status':'unsupported','provider':'geetest','reason':reason,
                'message':'PRIVATE_RUNNER_MESSAGE'}
    bridge,_,_=_bridge(backend,runner=runner)
    handle=bridge.connect({'endpoint':ENDPOINT})['targets'][0]['id']
    output=bridge.run({'target':handle,'request_id':str(uuid.uuid4())})
    assert expected in output['result']['message']
    assert 'PRIVATE_' not in json.dumps(output)
    assert set(output['result']) == {'status','provider','elapsed_ms','message'}


def test_request_replay_is_cached_and_id_cannot_move_to_other_target(backend):
    targets = [{"id": "tab-a", "title": "A", "url": FULL_URL},
               {"id": "tab-b", "title": "B", "url": "https://example.invalid/other"}]
    calls = []
    bridge, _, _ = _bridge(backend, snapshot=_snapshot(targets=targets),
                           runner=lambda record, event: (calls.append(record) or _result()))
    handles = [item["id"] for item in bridge.connect({"endpoint": ENDPOINT})["targets"]]
    request_id = str(uuid.uuid4())
    first = bridge.run({"target": handles[0], "request_id": request_id})
    assert bridge.run({"target": handles[0], "request_id": request_id}) == first
    assert len(calls) == 1
    with pytest.raises(backend.BridgeError) as exc:
        bridge.run({"target": handles[1], "request_id": request_id})
    _assert_error(exc, (409,))
    assert len(calls) == 1


def test_busy_rejects_second_run_and_connect_then_recovers(backend):
    targets = [{"id": "tab-a", "title": "A", "url": FULL_URL},
               {"id": "tab-b", "title": "B", "url": "https://example.invalid/other"}]
    started, release, first = threading.Event(), threading.Event(), {}

    def runner(record, cancel_event):
        started.set()
        assert release.wait(3)
        return _result()

    bridge, _, _ = _bridge(backend, snapshot=_snapshot(targets=targets), runner=runner)
    handles = [item["id"] for item in bridge.connect({"endpoint": ENDPOINT})["targets"]]
    worker = threading.Thread(target=lambda: first.setdefault("output", bridge.run(
        {"target": handles[0], "request_id": str(uuid.uuid4())})))
    worker.start()
    try:
        assert started.wait(2) and bridge.busy
        with pytest.raises(backend.BridgeError) as exc:
            bridge.run({"target": handles[1], "request_id": str(uuid.uuid4())})
        _assert_error(exc, (409,))
        with pytest.raises(backend.BridgeError) as exc:
            bridge.connect({"endpoint": ENDPOINT})
        _assert_error(exc, (409,))
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and first["output"]["ok"] and not bridge.busy


def test_cancel_wrong_id_is_rejected_correct_id_sets_event_and_recovers(backend):
    events, first = [], {}

    def runner(record, cancel_event):
        events.append(cancel_event)
        if len(events) == 1:
            assert cancel_event.wait(2)
            return {'status':'unsupported','provider':'geetest','reason':'no_provider'}
        return _result()

    bridge, _, _ = _bridge(backend, runner=runner)
    handle = bridge.connect({"endpoint": ENDPOINT})["targets"][0]["id"]
    request_id = str(uuid.uuid4())
    worker = threading.Thread(target=lambda: first.setdefault("output", bridge.run(
        {"target": handle, "request_id": request_id})))
    worker.start()
    try:
        assert events == [] or len(events) == 1
        while not events:
            assert worker.is_alive()
        with pytest.raises(backend.BridgeError) as exc:
            bridge.cancel({"request_id": str(uuid.uuid4())})
        _assert_error(exc, (409,))
        assert not events[0].is_set()
        assert bridge.cancel({"request_id": request_id})["ok"] is True
    finally:
        events[0].set() if events else None
        worker.join(timeout=3)
    assert not worker.is_alive() and first["output"]["result"]["status"] == "cancelled"
    assert first['output']['result']['message'] == backend.MESSAGES['cancelled']
    assert bridge.run({"target": handle, "request_id": str(uuid.uuid4())})["ok"] is True

def test_runner_exception_is_masked_and_lock_releases(backend):
    failing, calls, secret = [True], [], "PRIVATE_RUNNER_EXCEPTION"

    def runner(record, cancel_event):
        calls.append(record)
        if failing[0]:
            raise RuntimeError(secret)
        return _result()

    bridge, _, _ = _bridge(backend, runner=runner)
    handle = bridge.connect({"endpoint": ENDPOINT})["targets"][0]["id"]
    request_id = str(uuid.uuid4())
    first = bridge.run({"target": handle, "request_id": request_id})
    assert first["ok"] and first["result"]["status"] == "unknown"
    assert secret not in json.dumps(first) and not bridge.busy
    assert bridge.run({"target": handle, "request_id": request_id}) == first
    assert len(calls) == 1
    failing[0] = False
    recovered = bridge.run({"target": handle, "request_id": str(uuid.uuid4())})
    assert recovered["ok"] and recovered["result"]["status"] == "passed"
    assert len(calls) == 2 and not bridge.busy
