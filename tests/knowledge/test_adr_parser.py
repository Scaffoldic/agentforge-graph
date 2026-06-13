"""ADRParser golden tests (feat-010): MADR frontmatter, Nygard headings,
status/date/supersedes extraction, and filename fallback."""

from __future__ import annotations

from agentforge_graph.knowledge.adr import ADRParser

P = ADRParser()


def test_madr_frontmatter() -> None:
    text = (
        "---\ntitle: Use Kuzu\nstatus: Accepted\ndate: 2025-10-01\n"
        "superseded-by: 14\n---\n\n# Use Kuzu\n\n## Decision\n\nWe use Kuzu.\n"
    )
    adr = P.parse("docs/adr/0010-kuzu.md", text)
    assert adr.title == "Use Kuzu"
    assert adr.status == "accepted"  # normalised
    assert adr.date == "2025-10-01"
    assert adr.adr_id == "ADR-0010"
    assert adr.supersedes_num == "14"
    assert adr.well_formed


def test_nygard_sections() -> None:
    text = (
        "# 7. Old approach\n\nDate: 2024-02-10\n\n## Status\n\nSuperseded\n\n"
        "## Context\n\nWhy.\n\n## Decision\n\nSupersedes ADR-0003.\n"
    )
    adr = P.parse("docs/adr/0007-old.md", text)
    assert adr.title == "7. Old approach"
    assert adr.status == "superseded"
    assert adr.date == "2024-02-10"
    assert adr.supersedes_num == "3"
    assert {s.heading for s in adr.sections} >= {"Status", "Context", "Decision"}


def test_unknown_status_defaults_to_proposed() -> None:
    adr = P.parse("docs/adr/0001-x.md", "# Title only\n\nNo status here.\n")
    assert adr.status == "proposed"
    assert adr.date == ""
    assert adr.supersedes_num == ""


def test_filename_fallback_when_no_title() -> None:
    adr = P.parse("docs/adr/0009-event-sourcing.md", "no headings, no frontmatter\n")
    assert adr.title == "0009 event sourcing"
    assert adr.well_formed is False  # degraded, not dropped


def test_malformed_frontmatter_degrades() -> None:
    adr = P.parse("docs/adr/0002-x.md", "---\n: : bad yaml [[[\n---\n# Real Title\n")
    # bad frontmatter → fall through to heading scan, still parses
    assert adr.title == "Real Title"
