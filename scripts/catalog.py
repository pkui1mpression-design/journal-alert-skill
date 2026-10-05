"""Journal catalog: resolve user-supplied journal hints into fetchable entries.

A catalog entry looks like::

    {"name": "Nature", "issn": "0028-0836", "rss": "https://...", "aliases": ["nature"]}

``issn`` is the only field the fetcher really needs (OpenAlex and Crossref both
key off it); ``rss`` may be empty, in which case the feed source is silently
skipped and the two APIs carry the journal.

Resolution accepts, for each requested journal:

* a catalog **name** (case-insensitive, punctuation-insensitive)
* an **alias**
* an **ISSN** (with or without the dash, any case)
* a **substring** of a name, as a last resort (``"atmospheric"`` → matches more
  than one journal, all of which are returned)
* an inline **dict** ``{"name": ..., "issn": ..., "rss": ...}`` for journals not
  in the catalog — the agent looks the ISSN up and passes it through.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "journals.json"

_ISSN_RE = re.compile(r"^\d{4}-?\d{3}[\dxX]$")


def _norm(text: str) -> str:
    """Lower-case and strip everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def load_catalog(path: str | Path | None = None) -> dict:
    data = json.loads(Path(path or CATALOG_PATH).read_text(encoding="utf-8"))
    journals = data.get("journals") or []
    for entry in journals:
        entry.setdefault("aliases", [])
        entry.setdefault("rss", "")
        entry.setdefault("enabled", True)
    return {"journals": journals}


def default_journals(catalog: dict) -> list[dict]:
    picked = [j for j in catalog["journals"] if j.get("default")]
    return picked or list(catalog["journals"])


def _index(catalog: dict) -> tuple[dict, dict]:
    by_name: dict[str, dict] = {}
    by_issn: dict[str, dict] = {}
    for entry in catalog["journals"]:
        for key in [entry["name"], *entry.get("aliases", [])]:
            if key:
                by_name.setdefault(_norm(key), entry)
        if entry.get("issn"):
            by_issn[_norm(entry["issn"])] = entry
    return by_name, by_issn


def resolve_journals(selection, catalog: dict) -> tuple[list[dict], list[str]]:
    """Return ``(journals, unresolved_hints)``.

    ``selection`` may be ``None``/empty (→ the default set), the string
    ``"all"``/``"default"``, a single string, or a list mixing strings and dicts.
    """
    by_name, by_issn = _index(catalog)
    all_journals = list(catalog["journals"])

    if selection in (None, "", [], ()):
        return default_journals(catalog), []

    if isinstance(selection, str):
        if selection.strip().lower() in ("all", "*"):
            return all_journals, []
        if selection.strip().lower() in ("default", "默认"):
            return default_journals(catalog), []
        selection = [selection]

    picked: list[dict] = []
    seen_issns: set[str] = set()
    unresolved: list[str] = []

    def add(entry: dict) -> None:
        key = _norm(entry.get("issn") or entry["name"])
        if key in seen_issns:
            return
        seen_issns.add(key)
        picked.append(entry)

    for hint in selection:
        if isinstance(hint, dict):
            name = (hint.get("name") or "").strip()
            issn = (hint.get("issn") or "").strip()
            if not name or not issn:
                unresolved.append(json.dumps(hint, ensure_ascii=False))
                continue
            add({"name": name, "issn": issn, "rss": hint.get("rss", ""), "aliases": [], "enabled": True})
            continue

        text = str(hint).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in ("all", "*"):
            for entry in all_journals:
                add(entry)
            continue
        key = _norm(text)
        if _ISSN_RE.match(text):
            found = by_issn.get(key)
            if found:
                add(found)
            else:
                unresolved.append(text)
            continue
        found = by_name.get(key)
        if found:
            add(found)
            continue
        partial = [j for j in all_journals if key and key in _norm(j["name"])]
        if partial:
            for entry in partial:
                add(entry)
            continue
        unresolved.append(text)

    return picked, unresolved
