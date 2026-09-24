"""M3 invariants: egress gate, OpenRouter policy, verifier, prompt registry."""
import json

import httpx
import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.egress.gate import EgressDenied, EgressGate
from mw.llm.openrouter import OpenRouterClient, ProviderPolicy, RoleConfig
from mw.llm.prompts import PromptRegistry
from mw.llm.verifier import verify

from conftest import REPO

SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEK"


def test_gate_blocks_coords_sequence_paths(tmp_path):
    g = EgressGate(tmp_path / "egress.jsonl", mode="online")
    clean, blocked = g.sanitize({
        "state": {"n_hbond": 12, "coords": [[1, 2, 3]], "note": f"chain A is {SEQ}",
                  "atoms_xyz": [[0.1, 0.2, 0.3], [1, 1, 1], [2, 2, 2]]},
        "msg": "see /home/me/secret/7xyz.cif for details",
    })
    s = json.dumps(clean)
    assert "coords" not in clean["state"] and SEQ not in s and "/home/me" not in s
    assert clean["state"]["n_hbond"] == 12
    assert len(blocked) == 4


def test_local_only_denies_and_logs(tmp_path):
    g = EgressGate(tmp_path / "egress.jsonl", mode="local_only")
    with pytest.raises(EgressDenied):
        g.send("openrouter:x", {"a": 1}, purpose="test")
    with pytest.raises(EgressDenied):
        g.fetch("https://files.rcsb.org/download/7XYZ.cif", purpose="load_structure")
    lines = (tmp_path / "egress.jsonl").read_text().splitlines()
    assert len(lines) == 2 and all(json.loads(l)["sent"] is False for l in lines)


def _client(tmp_path, handler):
    gate = EgressGate(tmp_path / "egress.jsonl", mode="online")
    return OpenRouterClient(gate, tmp_path / "cache", transport=httpx.MockTransport(handler), api_key="sk-secret")


def test_request_policy_served_model_and_cache(tmp_path):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        return httpx.Response(200, json={"model": "typesafe/jev-1.12",
                                         "choices": [{"message": {"content": '{"choice":"relax"}'}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
    c = _client(tmp_path, handler)
    cfg = RoleConfig(role="jev", model="typesafe/jev-1.13")
    msgs = [{"role": "user", "content": "decide"}]
    r = c.complete(cfg, msgs, response_schema={"title": "d", "type": "object"}, purpose="jev.decide")
    body = seen[0]
    assert body["provider"]["data_collection"] == "deny" and body["provider"]["zdr"] is True
    assert body["provider"]["allow_fallbacks"] is False and "models" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert r.parsed == {"choice": "relax"} and r.served_matches_pin is False
    r2 = c.complete(cfg, msgs, response_schema={"title": "d", "type": "object"}, purpose="jev.decide")
    assert r2.cached and len(seen) == 1
    assert "sk-secret" not in (tmp_path / "egress.jsonl").read_text()


@pytest.mark.parametrize("code,cls", [(429, FailureClass.transient), (503, FailureClass.transient),
                                      (402, FailureClass.fatal), (400, FailureClass.input_invalid)])
def test_http_status_mapping(tmp_path, code, cls):
    c = _client(tmp_path, lambda req: httpx.Response(code, json={"error": "x"}))
    with pytest.raises(ToolFailure) as e:
        c.complete(RoleConfig(role="jev", model="m"), [{"role": "user", "content": str(code)}], purpose="t")
    assert e.value.cls == cls


def test_fallbacks_only_when_enabled():
    cfg = RoleConfig(role="frontier", model="a/b", fallback_models=["c/d"],
                     provider=ProviderPolicy(allow_fallbacks=True))
    body = OpenRouterClient.build_body(None, cfg, [])  # type: ignore[arg-type]
    assert body["models"] == ["a/b", "c/d"]


def test_verifier_drops_only_bad_sentences():
    text = "D100A와 리간드 사이 수소결합은 2.80 Å입니다. L48A는 ΔΔG −1.9 REU로 가장 안정합니다. 후보는 두 개입니다."
    v = verify(text, evidence=[2.8, 0.42, 12])
    assert [s.kept for s in v] == [True, False, True]


def test_prompt_registry_hash_and_vars():
    reg = PromptRegistry(REPO / "prompts")
    t = reg.get("frontier.plan")
    text, sha = t.render(goal="g", compact_state="{}", tools="[]", budget="{}")
    assert len(sha) == 12 and "g" in text
    with pytest.raises(KeyError):
        t.render(goal="g")
