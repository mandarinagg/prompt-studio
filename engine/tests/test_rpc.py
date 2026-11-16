import io
import json
import subprocess
import sys

import numpy as np
import pytest
import pyvips

from pstudio.rpc import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    handle_line,
    serve,
)


def call(method, params=None, req_id=1):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return handle_line(json.dumps(req))


def test_ping():
    assert call("ping") == {"jsonrpc": "2.0", "id": 1, "result": "pong"}


def test_version_reports_libvips():
    result = call("engine.version")["result"]
    assert result["python"].startswith("3.12")
    assert result["libvips"].count(".") == 2


def test_image_info(tmp_path):
    path = tmp_path / "small.png"
    pyvips.Image.new_from_array(np.zeros((30, 40, 3), dtype=np.uint8)).write_to_file(str(path))
    assert call("image.info", {"path": str(path)})["result"] == {
        "width": 40,
        "height": 30,
        "bands": 3,
        "format": "uchar",
    }


def test_image_info_missing_file_does_not_leak_full_path(tmp_path):
    err = call("image.info", {"path": str(tmp_path / "nope.jpg")})["error"]
    assert "nope.jpg" in err["message"] and str(tmp_path) not in err["message"]


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("{not json", PARSE_ERROR),
        ('{"jsonrpc": "1.0", "id": 1, "method": "ping"}', INVALID_REQUEST),
        ("[1, 2]", INVALID_REQUEST),
        ('{"jsonrpc": "2.0", "id": 1, "method": "eval"}', METHOD_NOT_FOUND),
        ('{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1]}', INVALID_PARAMS),
        ('{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": 1}}', INVALID_PARAMS),
    ],
)
def test_errors(line, code):
    assert handle_line(line)["error"]["code"] == code


def test_notification_gets_no_response():
    assert handle_line('{"jsonrpc": "2.0", "method": "ping"}') is None


def test_serve_loop_skips_blank_lines():
    stdin = io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\n\n')
    stdout = io.StringIO()
    serve(stdin, stdout)
    assert json.loads(stdout.getvalue()) == {"jsonrpc": "2.0", "id": 7, "result": "pong"}


def test_cli_rpc_process_end_to_end():
    proc = subprocess.run(
        [sys.executable, "-m", "pstudio", "rpc"],
        input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(proc.stdout) == {"jsonrpc": "2.0", "id": 1, "result": "pong"}
