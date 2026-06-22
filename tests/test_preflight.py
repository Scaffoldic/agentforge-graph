"""ENH-026: fail-fast config preflight + `ckg doctor`.

A selected driver whose optional dependency is missing (or whose credential env
var is unset) is caught *before* any indexing/embedding work, with the exact fix.
Probes are monkeypatched so the tests are independent of which extras happen to
be installed in the running environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph import preflight as pf
from agentforge_graph.cli import main
from agentforge_graph.config import EmbedConfig, EnrichConfig, ResolvedConfig, StoreConfig


@pytest.fixture
def all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate no optional extras installed (every probe module absent)."""
    monkeypatch.setattr(pf, "_module_present", lambda _m: False)


@pytest.fixture
def all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "_module_present", lambda _m: True)


# --- requirement table + install command ------------------------------------


def test_install_command_format() -> None:
    assert pf.install_command("bedrock") == "pip install 'agentforge-graph[bedrock]'"


def test_base_drivers_need_no_extra() -> None:
    for base in ("fake", "kuzu", "lancedb", "scripted", "anthropic"):
        assert pf.missing_extra(base) is None


def test_missing_extra_reports_module_and_extra(all_missing: None) -> None:
    assert pf.missing_extra("bedrock") == ("boto3", "bedrock")
    assert pf.missing_extra("openai") == ("openai", "openai")


def test_present_extra_is_not_missing(all_present: None) -> None:
    assert pf.missing_extra("bedrock") is None


# --- ProviderUnavailable (in-process guard) ---------------------------------


def test_ensure_installed_raises_with_install_cmd(all_missing: None) -> None:
    with pytest.raises(pf.ProviderUnavailable) as exc:
        pf.ensure_installed("bedrock", "embedder")
    assert exc.value.install_cmd == "pip install 'agentforge-graph[bedrock]'"
    assert "pip install" in str(exc.value)


def test_ensure_installed_noop_when_present(all_present: None) -> None:
    pf.ensure_installed("bedrock", "embedder")  # no raise


# --- per-role checks --------------------------------------------------------


def test_check_embedder_flags_missing_driver(all_missing: None) -> None:
    probs = pf.check_embedder("web", EmbedConfig(driver="bedrock"))
    assert len(probs) == 1
    assert probs[0].is_error
    assert "bedrock" in probs[0].summary
    assert probs[0].fix == "pip install 'agentforge-graph[bedrock]'"


def test_check_embedder_skipped_when_disabled(all_missing: None) -> None:
    # ENH-023: a structure-only repo needs no embedder, so no probe runs
    assert pf.check_embedder("web", EmbedConfig(enabled=False, driver="bedrock")) == []


def test_check_embedder_flags_missing_credentials(
    all_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    probs = pf.check_embedder("web", EmbedConfig(driver="openai"))
    assert len(probs) == 1
    assert "OPENAI_API_KEY" in probs[0].summary
    assert probs[0].fix.startswith("export OPENAI_API_KEY")


def test_check_embedder_clean_when_present_and_credentialed(
    all_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert pf.check_embedder("web", EmbedConfig(driver="openai")) == []


def test_check_store_flags_both_drivers(all_missing: None) -> None:
    cfg = StoreConfig.model_validate(
        {"graph": {"driver": "neo4j"}, "vectors": {"driver": "pgvector"}}
    )
    probs = pf.check_store("web", cfg)
    assert {p.fix for p in probs} == {
        "pip install 'agentforge-graph[neo4j]'",
        "pip install 'agentforge-graph[pgvector]'",
    }


def test_check_store_clean_for_base_drivers(all_missing: None) -> None:
    # kuzu + lancedb are base — no extra needed even with everything "missing"
    assert pf.check_store("web", StoreConfig()) == []


def test_check_enrich_skipped_when_disabled(all_missing: None) -> None:
    assert pf.check_enrich("web", EnrichConfig(enabled=False)) == []


# --- preflight aggregation --------------------------------------------------


def test_preflight_store_only_is_clean_on_base(all_missing: None) -> None:
    rc = ResolvedConfig(section={})  # defaults: kuzu/lancedb store
    assert pf.preflight(rc, store=True, embed=False, enrich=False) == []


def test_preflight_embed_flags_missing(all_missing: None) -> None:
    rc = ResolvedConfig(section={"embed": {"driver": "bedrock"}})
    probs = pf.preflight(rc, embed=True)
    assert any("bedrock" in p.summary for p in probs)


# --- CLI gate + ckg doctor --------------------------------------------------


def test_index_embed_refuses_before_work(all_missing: None, tmp_path: Path, capsys) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    # default embed driver is bedrock; with the extra "missing", --embed must fail fast
    rc = main(["index", str(repo), "--embed"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "pip install 'agentforge-graph[bedrock]'" in err
    assert not (repo / ".ckg").exists()  # refused before indexing


def test_plain_index_passes_preflight(all_missing: None, tmp_path: Path) -> None:
    # no --embed → only the base store is checked → succeeds even with no extras
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n")
    assert main(["index", str(repo)]) == 0


def test_doctor_reports_problems(all_missing: None, tmp_path: Path, capsys) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    rc = main(["doctor", str(repo)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "pip install 'agentforge-graph[bedrock]'" in out
    assert "must be fixed" in out


def test_doctor_clean_when_ready(all_present: None, tmp_path: Path, capsys) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    rc = main(["doctor", str(repo)])
    assert rc == 0
    assert "config OK" in capsys.readouterr().out
