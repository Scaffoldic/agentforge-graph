"""BUG-003 regression: ADR discovery skips README/index/template pages that live
under the ADR globs but are not decisions."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.knowledge.ingest import KnowledgeIngestor


def test_discover_skips_readme_index_template(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "README.md").write_text("# Architecture Decision Records\n\nsuperseded ones live here\n")
    (adr / "index.md").write_text("# Index\n")
    (adr / "template.md").write_text("# Template\n")
    (adr / "0012-real.md").write_text("# 12. Real decision\n\n## Status\n\naccepted\n")

    discovered = KnowledgeIngestor("repo")._discover(tmp_path, ["docs/adr/**/*.md"])
    rels = {rel for rel, _ in discovered}
    assert rels == {"docs/adr/0012-real.md"}  # only the real ADR
