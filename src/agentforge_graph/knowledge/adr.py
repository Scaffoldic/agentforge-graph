"""``ADRParser`` — parse an architecture decision record markdown file into a
format-neutral ``ParsedADR`` (feat-010 MVP).

Tolerant of MADR (YAML frontmatter), Nygard, and adr-tools layouts: read a
frontmatter block if present, else scan headings/lines for the title, status,
date, and supersedes link. A file that yields no recognisable ADR shape still
becomes a ``Decision`` titled from its filename — degrade, never drop (spec §8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

_STATUSES = {"proposed", "accepted", "superseded", "deprecated", "rejected"}
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
# "Supersedes ADR-0007", "supersede 0007", "Superseded by ADR-0012"
_SUPERSEDES_RE = re.compile(r"supersedes?\s+(?:adr-?)?(\d+)", re.IGNORECASE)
_ADR_NUM_RE = re.compile(r"(\d+)")


@dataclass
class DocSection:
    heading: str
    text: str


@dataclass
class ParsedADR:
    title: str
    status: str = "proposed"
    date: str = ""
    adr_id: str = ""  # e.g. "ADR-0012" (from filename number or frontmatter)
    supersedes_num: str = ""  # the numeric id of a superseded ADR, if any
    body: str = ""
    sections: list[DocSection] = field(default_factory=list)
    well_formed: bool = True  # False → fell back to filename title


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n", 1)
    rest = parts[1] if len(parts) > 1 else ""
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    block = rest[:end]
    remainder = rest[end + len("\n---") :].lstrip("\n")
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), remainder


def _sections(body: str) -> list[DocSection]:
    sections: list[DocSection] = []
    heading = ""
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("#"):
            if buf or heading:
                sections.append(DocSection(heading=heading, text="\n".join(buf).strip()))
            heading = line.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    if buf or heading:
        sections.append(DocSection(heading=heading, text="\n".join(buf).strip()))
    return [s for s in sections if s.text or s.heading]


def _first_heading_title(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return ""


def _status_from(text: str) -> str:
    # a "Status: accepted" line, a "## Status\naccepted" section, or a bare word
    for raw in text.splitlines():
        low = raw.strip().lower().lstrip("#").strip()
        low = low.removeprefix("status:").strip()
        for token in re.split(r"[\s,]+", low):
            if token in _STATUSES:
                return token
    return ""


class ADRParser:
    name = "adr-parser"

    def parse(self, path: str, text: str) -> ParsedADR:
        fm, body = _split_frontmatter(text)
        stem = PurePosixPath(path).stem
        num_match = _ADR_NUM_RE.search(stem)
        adr_id = f"ADR-{int(num_match.group(1)):04d}" if num_match else ""

        title = str(fm.get("title") or _first_heading_title(body) or "").strip()
        well_formed = bool(title)
        if not title:
            title = stem.replace("-", " ").replace("_", " ").strip() or path

        status = str(fm.get("status") or "").strip().lower() or _status_from(body)
        status = status if status in _STATUSES else "proposed"

        date = str(fm.get("date") or "").strip()
        if not date:
            m = _DATE_RE.search(body)
            date = m.group(1) if m else ""

        supersedes_num = ""
        fm_sup = fm.get("superseded-by") or fm.get("supersedes")
        if fm_sup:
            m = _ADR_NUM_RE.search(str(fm_sup))
            supersedes_num = str(int(m.group(1))) if m else ""
        if not supersedes_num:
            m = _SUPERSEDES_RE.search(body)
            supersedes_num = str(int(m.group(1))) if m else ""

        return ParsedADR(
            title=title,
            status=status,
            date=date,
            adr_id=adr_id,
            supersedes_num=supersedes_num,
            body=body,
            sections=_sections(body),
            well_formed=well_formed,
        )
