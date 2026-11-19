import io
import json
import threading

from pydantic import BaseModel

from pstudio.rpc import INVALID_PARAMS, METHODS, Notifier, handle_line


def call(method, params=None):
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    return handle_line(json.dumps(req))


def test_params_validated_by_model():
    err = call("image.info", {"path": 3})["error"]
    assert err["code"] == INVALID_PARAMS and "path" in err["message"]
    err = call("image.info", {"path": "x.jpg", "otro": 1})["error"]
    assert err["code"] == INVALID_PARAMS and "otro" in err["message"]


def test_methods_have_models():
    m = METHODS["image.info"]
    assert issubclass(m.params, BaseModel)
    assert "path" in m.params.model_fields


class _Evt(BaseModel):
    n: int


def test_emit_writes_notification_without_id():
    out = io.StringIO()
    Notifier(out).emit("thumbnail.ready", _Evt(n=1))
    msg = json.loads(out.getvalue())
    assert msg == {"jsonrpc": "2.0", "method": "thumbnail.ready", "params": {"n": 1}}


def test_notifier_is_thread_safe():
    out = io.StringIO()
    notifier = Notifier(out)

    def work():
        for i in range(50):
            notifier.emit("e", _Evt(n=i))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = out.getvalue().splitlines()
    assert len(lines) == 400
    assert all(json.loads(line)["method"] == "e" for line in lines)
