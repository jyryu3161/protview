from pathlib import Path

import pytest

from mw.core.contracts import ToolSpec
from mw.tools.registry import ToolRegistry
from mw.workspace import build_registry, new_run

FIX = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def pdb_path() -> str:
    return str(FIX / "mini_complex.pdb")


@pytest.fixture
def run(tmp_path):
    return new_run(tmp_path, dry_run=True, run_id="run_test")


@pytest.fixture
def fake_registry() -> ToolRegistry:
    """A tiny registry with controllable tools for runtime tests."""
    specs = {
        "make": ToolSpec(name="make", level="L2", emits="thing", params={"x": {"type": "int", "default": 1}}),
        "flaky": ToolSpec(name="flaky", level="L2", emits="thing"),
        "bad": ToolSpec(name="bad", level="L2", emits="thing"),
        "costly": ToolSpec(name="costly", level="L3", emits="thing", cost_class="expensive"),
    }
    return ToolRegistry(specs)
