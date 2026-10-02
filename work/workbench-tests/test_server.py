import base64
import http.client
import importlib.util
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = ROOT / "outputs/Slidex工作台.app/Contents/Resources/server.py"
RESULT_KEYS = {"success", "gap_x", "gap_box", "confidence", "method", "elapsed_ms",
               "image_width", "image_height"}

def _load_backend():
    assert SERVER_PATH.is_file(), "server has not been implemented"
    spec = importlib.util.spec_from_file_location("slidex_workbench_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.fixture(scope="module")
def backend():
    return _load_backend()

@pytest.fixture(scope="module")
def image():
    ok, encoded = cv2.imencode(".png", np.zeros((12, 16, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()

def _payload(image, piece=None):
    encode = lambda value: None if value is None else base64.b64encode(value).decode("ascii")
    return {"image": encode(image), "piece": encode(piece)}

def _result():
    return {"success": True, "gap_x": 4, "gap_box": [1, 2, 5, 8], "confidence": 0.91,
            "method": "test", "elapsed_ms": 3, "image_width": 16, "image_height": 12}

@contextmanager
def _running(backend, analyzer):
    server = backend.WorkbenchServer(("127.0.0.1", 0), analyzer=analyzer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()

def _exchange(server, body, *, token=None, origin=None, host=None, transmit=True, content_length=None, path='/api/analyze'):
    body = body.encode() if isinstance(body, str) else body
    port = server.server_address[1]
    headers = {
        "Host": f"127.0.0.1:{port}" if host is None else host,
        "Origin": f"http://127.0.0.1:{port}" if origin is None else origin,
        "X-Workbench-Token": server.token if token is None else token,
        "Content-Type": "application/json", "Content-Length": str(len(body) if content_length is None else content_length),
        "Connection": "close",
    }
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.putrequest("POST", path, skip_host=True)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders(body if transmit else None)
        response = connection.getresponse()
        raw = response.read()
        return response.status, (json.loads(raw) if raw else None), raw
    finally:
        connection.close()

def _assert_error(data):
    assert set(data) == {"ok", "error"} and data["ok"] is False
    assert set(data["error"]) == {"code", "message"}
    assert all(isinstance(data["error"][key], str) for key in ("code", "message"))

@pytest.mark.parametrize("case", ["malformed", "null", "missing", "null_image", "unknown", "bad_base64", "path"])
def test_rejects_invalid_or_non_object_json(backend, image, case):
    if case == "malformed":
        body = b"{"
    elif case == "null":
        body = b"null"
    else:
        payload = _payload(image)
        if case == "missing":
            del payload["image"]
        elif case == "null_image":
            payload["image"] = None
        elif case == "unknown":
            payload["extra"] = "reject"
        else:
            payload["image"] = "!!!" if case == "bad_base64" else "/private/tmp/image.png"
        body = json.dumps(payload).encode()
    calls = []
    with _running(backend, lambda payload: calls.append(payload)) as server:
        status, data, _ = _exchange(server, body)
    assert status == 400
    _assert_error(data)
    assert calls == []

@pytest.mark.parametrize("field", ["token", "origin", "host"])
def test_rejects_wrong_auth_origin_or_host(backend, image, field):
    values = {"token": "wrong-token", "origin": "http://localhost:1", "host": "localhost"}
    with _running(backend, lambda payload: _result()) as server:
        status, data, _ = _exchange(server, json.dumps(_payload(image)), **{field: values[field]})
    assert status == 403
    _assert_error(data)

def test_rejects_declared_body_over_limit_without_upload(backend, image):
    calls = []
    with _running(backend, lambda payload: calls.append(payload)) as server:
        status, data, _ = _exchange(server, json.dumps(_payload(image)), transmit=False,
                                    content_length=backend.MAX_BODY + 1)
    assert status == 413
    _assert_error(data)
    assert calls == []

@pytest.mark.parametrize("kind", ["image_size", "pixels", "corrupt"])
def test_rejects_invalid_image_limits_or_bytes(backend, kind):
    if kind == "image_size":
        image = b"x" * (backend.MAX_IMAGE + 1)
        expected = 413
    elif kind == "pixels":
        ok, encoded = cv2.imencode(".jpg", np.zeros((3001, 4000, 3), dtype=np.uint8))
        assert ok
        image, expected = encoded.tobytes(), 413
    else:
        image, expected = b"not-an-image", 422
    with _running(backend, lambda payload: _result()) as server:
        status, data, _ = _exchange(server, json.dumps(_payload(image)))
    assert status == expected
    _assert_error(data)

def test_second_request_is_busy_while_first_analyzer_runs(backend, image):
    started, release = threading.Event(), threading.Event()

    def analyzer(payload):
        started.set()
        assert release.wait(3)
        return _result()

    first = {}
    with _running(backend, analyzer) as server:
        request = json.dumps(_payload(image))
        worker = threading.Thread(target=lambda: first.setdefault("response", _exchange(server, request)))
        worker.start()
        try:
            assert started.wait(2)
            status, data, _ = _exchange(server, request)
            assert status == 409
            _assert_error(data)
        finally:
            release.set()
            worker.join(timeout=3)
        assert not worker.is_alive()
    assert first["response"][0] == 200

def test_repeated_pure_requests_return_equivalent_results(backend, image):
    calls = []

    def analyzer(payload):
        calls.append(payload)
        return _result()

    with _running(backend, analyzer) as server:
        first = _exchange(server, json.dumps(_payload(image)))
        second = _exchange(server, json.dumps(_payload(image)))
    assert first[0] == second[0] == 200
    assert first[1]["result"] == second[1]["result"]
    assert len(calls) == 2
    assert calls == [{"image": image, "piece": None}, {"image": image, "piece": None}]

def test_timeout_releases_busy_lock_and_recovers(backend, image):
    attempts = []

    def analyzer(payload):
        if not attempts:
            attempts.append(True)
            raise TimeoutError("TIMEOUT_SECRET")
        return _result()

    with _running(backend, analyzer) as server:
        first = _exchange(server, json.dumps(_payload(image)))
        second = _exchange(server, json.dumps(_payload(image)))
    assert first[0] == 504
    _assert_error(first[1])
    assert b"TIMEOUT_SECRET" not in first[2]
    assert second[0] == 200

def test_masks_analyzer_exception_and_whitelists_result_fields(backend, image):
    secret = "PRIVATE_ANALYZER_SECRET"

    def failing(_):
        raise RuntimeError(secret)

    with _running(backend, failing) as server:
        status, data, raw = _exchange(server, json.dumps(_payload(image)))
    assert status == 500
    _assert_error(data)
    assert secret.encode() not in raw

    def extra_fields(payload):
        result = _result()
        result.update(secret=secret, debug_path="/private/input.png")
        return result

    with _running(backend, extra_fields) as server:
        status, data, raw = _exchange(server, json.dumps(_payload(image, image)))
    assert status == 200
    assert set(data) == {"ok", "result", "notice"}
    assert data["ok"] is True and isinstance(data["notice"], str)
    assert set(data["result"]) == RESULT_KEYS
    assert secret.encode() not in raw
