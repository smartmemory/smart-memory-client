import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("core_source", "error"),
    [
        pytest.param(
            "import n4_cliwire_missing_dependency\n",
            "ModuleNotFoundError: No module named 'n4_cliwire_missing_dependency'",
            id="missing-dependency",
        ),
        pytest.param(
            "raise ImportError('n4_cliwire broken core')\n",
            "ImportError: n4_cliwire broken core",
            id="import-error",
        ),
    ],
)
def test_verify_client_reports_broken_core(tmp_path, core_source, error):
    core = tmp_path / "smartmemory"
    core.mkdir()
    (core / "__init__.py").write_text(core_source, encoding="utf-8")
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, str(root / "verify_client.py")],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0, result.stdout
    assert error in result.stderr
    assert result.stdout == ""
