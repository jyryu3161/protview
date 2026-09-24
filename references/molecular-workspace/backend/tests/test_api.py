from fastapi.testclient import TestClient


def test_human_command_goes_through_orchestrator(tmp_path, monkeypatch, pdb_path):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path)
    c = TestClient(appmod.app)
    rid = c.post("/runs", json={"goal": "look at the pocket"}).json()["run_id"]
    r = c.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {"source": pdb_path}}).json()
    assert r["ok"] and r["handle"]["kind"] == "structure"
    bad = c.post(f"/runs/{rid}/commands", json={"tool": "relax_structure", "args": {"structure": r["handle"]["handle"]}}).json()
    assert bad["ok"] is False and bad["error"] == "precondition" and bad["fix"]["tool"] == "prepare_structure"
    evs = c.get(f"/runs/{rid}/events").json()
    called = [e for e in evs if e["type"] == "tool_called"]
    assert called[0]["decided_by"] == "human"
