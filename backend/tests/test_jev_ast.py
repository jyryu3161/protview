"""M24 T5 source-structure checks for the JEV science channel (spec .dryforge/spec.md 5, 10; handoff conditions 2, 5).

(a) ``request_science`` is called from ``jev_sends.run_send`` only (plus the gate's own one-line delegate to
    ``mw.egress.science``), and ``run_send`` is called from one HTTP route only: ``POST /runs/{rid}/jev/sends``. No
    tool, job, M13 flow, viewer, report or ``Run.call`` path reaches it.
(b) An ``httpx`` client is built (and ``httpx`` imported) only inside ``backend/mw/egress/``.
(c) The new modules never name the limit-raise functions, so the three existing limit-raise AST tests keep their
    caller sets.
(d) The four science event types are written only by ``jev_sends.py`` and ``egress/science.py``.
Static reads of the source only; nothing is run.
"""
from __future__ import annotations

import ast
from pathlib import Path

from mw import jev_constants as J
from mw.api import app as api_module

MW = Path(__file__).resolve().parents[1] / "mw"
NEW_MODULES = ("jev_constants.py", "jev_projection.py", "jev_sends.py", "jev_reports.py", "egress/science.py",
               "tools/jev.py")
EVENT_NAMES = {J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME}
EVENT_ATTRS = {"EVENT_CONSENT", "EVENT_APPROVED", "EVENT_DISPATCH", "EVENT_OUTCOME"}
HTTP_CLIENT_NAMES = {"AsyncClient", "Client", "request", "stream", "get", "post", "put", "patch", "delete", "head",
                     "options", "AsyncHTTPTransport", "HTTPTransport"}


def _sources():
    for path in sorted(MW.rglob("*.py")):
        yield str(path.relative_to(MW)), ast.parse(path.read_text(encoding="utf-8"))


def _owners(tree):
    """node -> qualified name of the innermost enclosing function (``Class.method``), or ``<module>``."""
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = child.name if name == "<module>" else f"{name}.{child.name}"
                owner[child] = name
                visit(child, inner)
            else:
                owner[child] = name
                visit(child, name)
    visit(tree, "<module>")
    return owner


def _called(node):
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _references(name):
    """(file, enclosing function, 'call' | 'ref') for every Name / Attribute spelled ``name`` in backend/mw."""
    found = set()
    for rel, tree in _sources():
        owner = _owners(tree)
        calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call) and _called(node) == name}
        for node in ast.walk(tree):
            spelled = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if spelled == name:
                found.add((rel, owner[node], "call" if id(node) in calls else "ref"))
    return found


# ---------------------------------------------------------------- (a) the one send path


def test_request_science_is_called_only_by_run_send_through_the_gate():
    assert _references("request_science") == {
        ("jev_sends.py", "run_send", "call"),                          # gate.request_science(run, content, ...)
        ("egress/gate.py", "EgressGate.request_science", "call"),       # the gate's delegate to egress/science.py
    }
    gate = ast.parse((MW / "egress/gate.py").read_text())
    method = next(node for node in ast.walk(gate) if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "request_science")
    statements = [node for node in method.body if not (isinstance(node, ast.Expr) and
                                                        isinstance(node.value, ast.Constant))]
    assert [type(node) for node in statements] == [ast.ImportFrom, ast.Return]   # import + return await, nothing else
    assert statements[0].module == "science" and [a.name for a in statements[0].names] == ["request_science"]


def test_run_send_is_called_only_by_the_approval_route():
    assert _references("run_send") == {("api/app.py", "jev_send_create", "call")}
    routes = [(route.path, sorted(route.methods), route.endpoint.__name__) for route in api_module.app.routes
              if getattr(route, "endpoint", None) is not None and route.endpoint.__name__ == "jev_send_create"]
    assert routes == [("/runs/{rid}/jev/sends", ["POST"], "jev_send_create")]
    # The route uses the module-level science gate, which nothing else in the server touches.
    assert {(rel, owner) for rel, owner, _ in _references("SCIENCE_GATE")} == {("api/app.py", "jev_send_create"),
                                                                              ("api/app.py", "<module>")}
    importers = {rel for rel, tree in _sources() for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("jev_sends")
                 or isinstance(node, ast.ImportFrom) and any(alias.name == "jev_sends" for alias in node.names)}
    assert importers == {"api/app.py", "egress/science.py", "jev_reports.py"}


def test_no_tool_job_flow_viewer_or_report_module_names_the_send_functions():
    for rel, tree in _sources():
        if rel.startswith(("tools/", "jobs/", "runtime/")) or rel in {
                "analysis_executions.py", "analysis_plans.py", "workflows.py", "viewer_intents.py",
                "egress/viewer.py", "jev_reports.py"}:
            names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
                     if isinstance(node, (ast.Name, ast.Attribute))}
            assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send"}, rel


# ---------------------------------------------------------------- (b) httpx stays inside egress/


def test_httpx_is_imported_and_clients_are_built_only_inside_egress():
    imports, built = set(), set()
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "httpx" for alias in node.names):
                imports.add(rel)
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "httpx":
                imports.add(rel)
            if (isinstance(node, ast.Attribute) and node.attr in HTTP_CLIENT_NAMES
                    and isinstance(node.value, ast.Name) and node.value.id == "httpx"):
                built.add(rel)
    assert imports and all(rel.startswith("egress/") for rel in imports), imports
    assert built == {"egress/gate.py"}, built
    for rel in NEW_MODULES:
        text = (MW / rel).read_text()
        tree = ast.parse(text)
        modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not {m for m in modules if m.split(".")[0] in {"urllib", "http", "requests", "socket", "aiohttp"}}, rel


# ---------------------------------------------------------------- (c) no new limit-raise name


def test_new_modules_never_name_the_limit_raise_functions():
    for rel in NEW_MODULES:
        text = (MW / rel).read_text()
        assert "raise_limits" not in text and "limit_approval" not in text, rel
    callers = {(rel, owner) for rel, owner, kind in _references("raise_limits") if kind == "call"}
    assert callers == {("docking_batch_jobs.py", "limit_approval"), ("ligand_ga_jobs.py", "limit_approval"),
                       ("sequence_ga_jobs.py", "limit_approval")}


# ---------------------------------------------------------------- (d) who writes the science events


def test_the_four_science_events_are_written_only_by_the_send_modules():
    writers, literals = set(), set()
    for rel, tree in _sources():
        owner = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in EVENT_NAMES:
                literals.add(rel)
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append" and node.args):
                continue
            first = node.args[0]
            if ((isinstance(first, ast.Constant) and first.value in EVENT_NAMES) or
                    (isinstance(first, ast.Attribute) and first.attr in EVENT_ATTRS) or
                    (isinstance(first, ast.Name) and first.id in EVENT_ATTRS)):
                writers.add((rel, owner[node], first.attr if isinstance(first, ast.Attribute) else ast.unparse(first)))
    assert literals == {"jev_constants.py", "core/events.py"}
    assert writers == {("jev_sends.py", "set_consent", "EVENT_CONSENT"), ("jev_sends.py", "run_send.admit",
                                                                         "EVENT_APPROVED"),
                       ("jev_sends.py", "_finish", "EVENT_OUTCOME"),
                       ("egress/science.py", "request_science", "EVENT_DISPATCH")}
