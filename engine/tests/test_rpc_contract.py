import json
from pathlib import Path

from pstudio.rpc import EVENTS, METHODS
from pstudio.rpc.contract import RPC_SCHEMA_FILE, rpc_json_schema

REPO = Path(__file__).resolve().parents[2]


def test_contract_lists_every_method_and_event():
    s = rpc_json_schema()
    methods = s["properties"]["methods"]["properties"]
    assert set(methods) == set(METHODS)
    assert set(s["properties"]["events"]["properties"]) == set(EVENTS)
    for spec in methods.values():
        assert set(spec["properties"]) == {"params", "result"}
    # Los $ref apuntan a $defs existentes.
    text = json.dumps(s)
    for ref in {r.split('"')[0] for r in text.split('"$ref": "#/$defs/')[1:]}:
        assert ref in s["$defs"], ref


def test_contract_params_are_strict():
    s = rpc_json_schema()
    params = s["properties"]["methods"]["properties"]["asset.set_stack"]["properties"]["params"]
    model = s["$defs"][params["$ref"].removeprefix("#/$defs/")]
    assert model["additionalProperties"] is False
    assert set(model["required"]) == {"asset", "stack", "label"}


def test_committed_rpc_schema_is_up_to_date():
    # Lo consume la app (app/scripts/gen-types.mjs → app/src/engine/contract.gen.ts).
    # Si falla: `uv run pstudio schema --rpc --out schema/rpc-1.schema.json`
    # y después `pnpm gen:types` en app/.
    assert REPO / "engine" / "schema" / "rpc-1.schema.json" == RPC_SCHEMA_FILE
    assert json.loads(RPC_SCHEMA_FILE.read_text(encoding="utf-8")) == rpc_json_schema()


def test_contract_has_draft_and_export():
    methods = rpc_json_schema()["properties"]["methods"]["properties"]
    assert {"plan.draft", "asset.export"} <= set(methods)
