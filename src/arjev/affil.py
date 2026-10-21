"""The who-line's affiliation seam (issue #87): authors as the feed reports
them, affiliations as the paper's own PDF prints them — a paper-level set,
never bound per author, dropped on parse ambiguity. Attribution doctrine in
ADR 0002: the paper's printed claim or human curation, never inference.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# the institution-likeliness filter: a candidate line must contain one of these.
# Broad by design — the paper claims the line; the parse only localizes it.
_INSTITUTION = re.compile(
    r"univer|institut|college|school|academy|polytechnic|laborator|cnrs|riken|"
    r"max[ -]planck|national|observatory|hospital|center|centre|corporation|"
    r"gmbh|\binc\b|\bltd\b|technolog|quantum ai|computing|research|foundation",
    re.IGNORECASE,
)
_DEPARTMENT = re.compile(r"^\s*(the\s+)?(department|dept)\b", re.IGNORECASE)
# the unambiguous institution words — prose rarely carries these, unlike
# "technologies" or "computing"; a >96-char line containing one is an
# affiliation, not the abstract's first line
_STRONG_INSTITUTION = re.compile(
    r"universit|institut|laborator|college|academy|polytechnic|cnrs|riken|max[ -]planck",
    re.IGNORECASE,
)
# address junk from the end: zips (either side of the format), state/country codes,
# and a closed country set — a trim rule, never a synonym map
_ADDRESS_TAIL = re.compile(
    r"\d|^[A-Z]{2,3}$|"
    r"^(the netherlands|united states|united kingdom|türkiye|germany|france|spain|italy|switzerland|"
    r"japan|china|canada|australia|denmark|sweden|norway|finland|austria|belgium|israel|"
    r"india|brazil|south korea|ireland|poland|portugal|singapore|taiwan)$",
    re.IGNORECASE,
)
_TRAILING_AND = re.compile(r"[;,]?\s*\b(and|&)\s*$", re.IGNORECASE)
_ABSTRACT = re.compile(r"^\s*abstract\b", re.IGNORECASE)
_MARKER = re.compile(r"^[\s\d\u00b9\u00b2\u00b3\u2070-\u209f*\u2020\u2021\u00a7()\[\]]+[.,]?\s*")
_DIGIT = re.compile(r"\d")


def _looks_like_author_list(line: str) -> bool:
    """A >96-char author list is not the abstract's first line: many comma
    segments, most carrying affiliation-digit markers (issue #87's long-roster
    papers put the whole author list on one line)."""
    segments = line.split(",")
    return len(segments) >= 4 and sum(1 for s in segments if _DIGIT.search(s)) >= 3


@dataclass
class WhoInfo:
    """Per-pick attribution for rendering. `hits` are tracked-people matches
    (name, curated group or None); `affiliations` are already tail-trimmed,
    deduped, and capped; `more_affiliations` is the k beyond the cap."""

    authors: list[str] = field(default_factory=list)
    hits: list[tuple[str, str | None]] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    more_affiliations: int = 0


def parse_affiliations(first_page_text: str) -> list[str]:
    """The paper-level affiliation set as printed on the first page: lines of the
    author block that read like institutions, with wrapped continuations merged,
    leading department segments and trailing address segments trimmed away —
    never a synonym map, never a name→institution binding. The block is bounded
    by the abstract heading when the paper prints one, else by the first long
    plain line (PRL-style abstracts flow without a heading); fail-open to []
    when neither boundary localizes a block.
    """
    lines = first_page_text.splitlines()[:40]
    boundary = 25  # the author block lives at the top; anything past 25 lines is not it
    for i, line in enumerate(lines):
        if _ABSTRACT.match(line):
            boundary = i
            break
        if len(line) > 96 and not _STRONG_INSTITUTION.search(line) and not _looks_like_author_list(line):
            boundary = i  # the full-width abstract's first line — prose, not an institution line
            break
    region = lines[:boundary]

    # merge wrapped affiliations: a region line ending in a comma continues
    merged: list[str] = []
    for line in region:
        if merged and merged[-1].endswith(","):
            merged[-1] = merged[-1] + " " + line.strip()
        else:
            merged.append(line.strip())

    seen: set[str] = set()
    affiliations: list[str] = []
    for line in merged:
        candidate = _TRAILING_AND.sub("", _MARKER.sub("", line))
        if not _INSTITUTION.search(candidate):
            continue
        segments = [s.strip() for s in candidate.split(",") if s.strip()]
        while segments and _DEPARTMENT.match(segments[0]):
            segments = segments[1:]  # drop the leading department prefix
        while segments and _ADDRESS_TAIL.search(segments[-1]):
            segments = segments[:-1]  # drop trailing zips, state/country codes
        if not segments:
            continue
        trimmed = ", ".join(segments)
        key = re.sub(r"\s+", " ", trimmed).lower()
        if key not in seen:
            seen.add(key)
            affiliations.append(trimmed)
    return affiliations


def build_who(authors: list[str], roster: list[str], arxiv: str, library_dir: Path | None,
              full: bool, fetcher=None) -> WhoInfo:
    """Assemble one pick's who-line data. Hits match the roster by the existing
    surname + first-initial rule (suffix ignored) and render the PRINTED author
    name with its curated group. In full mode affiliations come from the paper's
    own PDF via the library-cached fetch; any failure degrades to authors-only —
    it never blocks the post (issue #87's fail-open invariant)."""
    from .directives import split_group
    from .score import _name_match

    who = WhoInfo(authors=list(authors))
    seen_hits: set[str] = set()
    for author in authors:
        for entry in roster:
            if _name_match(entry, [author]) and author not in seen_hits:
                seen_hits.add(author)
                who.hits.append((author, split_group(entry)[1]))
    if full and library_dir is not None:
        try:
            from .keep import fetch_pdf
            from .paper_content import pdf_text

            path = fetch_pdf(arxiv, Path(library_dir), fetcher)
            affiliations = parse_affiliations("\n".join((pdf_text(path) or "").splitlines()[:40]))
            if len(affiliations) > 4:
                who.more_affiliations = len(affiliations) - 4
                affiliations = affiliations[:4]
            who.affiliations = affiliations
            if not affiliations:
                print(f"who-line: no affiliations parsed for {arxiv}", file=sys.stderr)
        except Exception as e:
            print(f"who-line degraded for {arxiv}: {type(e).__name__}: {e}", file=sys.stderr)
    return who
