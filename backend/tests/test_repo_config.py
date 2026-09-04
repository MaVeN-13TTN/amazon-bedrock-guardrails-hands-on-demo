"""Configuration that only misbehaves on a machine that has deployed.

`scripts/package-backend.sh` vendors every dependency into `backend/build/`, and
`terraform apply` runs it. So a contributor who has only ever run the tests sees a
clean lint, while anyone who has applied the Terraform sees ~7,000 errors in
third-party code and no way to find their own.

That was recorded as fixed in V-30 by excluding the directory in the
repository-root `pyproject.toml`. It was not fixed: ruff resolves configuration
per file from the nearest `pyproject.toml`, so everything under `backend/` is
governed by `backend/pyproject.toml`, and the root setting never applied.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _excludes(pyproject: pathlib.Path) -> list[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("ruff", {}).get("extend-exclude", [])


def test_the_backend_config_excludes_the_lambda_bundle():
    """The config ruff actually uses for backend/** must exclude the bundle."""
    excludes = _excludes(ROOT / "backend" / "pyproject.toml")

    assert "build" in excludes, (
        "backend/pyproject.toml must exclude 'build' — it is the config ruff "
        "resolves for files under backend/, and the root pyproject's exclusion "
        "of 'backend/build' never takes effect (V-30, V-33)."
    )
    assert "dist" in excludes


def test_the_root_config_still_excludes_it_too():
    """Kept for anyone invoking ruff on a path that resolves to the root config."""
    excludes = _excludes(ROOT / "pyproject.toml")

    assert "backend/build" in excludes
