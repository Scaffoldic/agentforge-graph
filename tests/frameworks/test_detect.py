"""Framework detection (feat-011): manifest deps, import-marker fallback,
explicit list, off, and the negative (no framework) path."""

from __future__ import annotations

from pathlib import Path

import yaml

from agentforge_graph.frameworks import active_frameworks, builtin_framework_registry

REG = builtin_framework_registry()
_PY = {".py"}


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _names(repo: Path, config: str | None = None) -> set[str]:
    return {p.name for p in active_frameworks(repo, config, REG, _PY)}


def test_detect_via_manifest(tmp_path: Path) -> None:
    _write(tmp_path, {"pyproject.toml": '[project]\ndependencies = ["fastapi", "uvicorn"]\n'})
    assert _names(tmp_path) == {"fastapi"}


def test_detect_via_import_marker_without_manifest(tmp_path: Path) -> None:
    _write(tmp_path, {"main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    assert _names(tmp_path) == {"fastapi"}


def test_no_framework_is_inactive(tmp_path: Path) -> None:
    _write(tmp_path, {"main.py": "def f():\n    return 1\n"})
    assert _names(tmp_path) == set()


def test_enabled_off_disables(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "pyproject.toml": '[project]\ndependencies = ["fastapi"]\n',
            "ckg.yaml": yaml.safe_dump({"frameworks": {"enabled": "off"}}),
        },
    )
    assert _names(tmp_path, str(tmp_path / "ckg.yaml")) == set()


def test_explicit_list_forces_pack(tmp_path: Path) -> None:
    # no fastapi anywhere, but explicitly enabled
    _write(
        tmp_path,
        {
            "main.py": "x = 1\n",
            "ckg.yaml": yaml.safe_dump({"frameworks": {"enabled": ["fastapi"]}}),
        },
    )
    assert _names(tmp_path, str(tmp_path / "ckg.yaml")) == {"fastapi"}


def test_force_enable_via_packs(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": "x = 1\n",
            "ckg.yaml": yaml.safe_dump({"frameworks": {"enabled": "auto", "packs": ["fastapi"]}}),
        },
    )
    assert _names(tmp_path, str(tmp_path / "ckg.yaml")) == {"fastapi"}


def test_detect_via_requirements_txt(tmp_path: Path) -> None:
    _write(tmp_path, {"requirements.txt": "# deps\nfastapi==0.110\n-e .\nuvicorn\n"})
    assert _names(tmp_path) == {"fastapi"}


def test_detect_via_poetry_deps(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.12"\nfastapi = "^0.110"\n'},
    )
    assert _names(tmp_path) == {"fastapi"}


def test_detect_via_optional_dependencies(tmp_path: Path) -> None:
    toml = '[project]\nname = "x"\n[project.optional-dependencies]\nweb = ["fastapi"]\n'
    _write(tmp_path, {"pyproject.toml": toml})
    assert _names(tmp_path) == {"fastapi"}


def test_malformed_pyproject_is_graceful(tmp_path: Path) -> None:
    _write(tmp_path, {"pyproject.toml": "this is = = not toml [[[", "main.py": "x = 1\n"})
    assert _names(tmp_path) == set()  # no crash, no false positive
