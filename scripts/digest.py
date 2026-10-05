#!/usr/bin/env python
"""journal-alert skill driver: keywords + journals in, literature digest out.

    python digest.py --keywords "microplastic, nanoplastic" --journals "Nature,ACP" --days 14
    python digest.py --spec spec.json --print
    python digest.py --list-journals
    python digest.py --check --journals "all"

The heavy lifting (RSS / OpenAlex / Crossref fetching, keyword scoring) is a
bundled copy of the journal-alert pipeline in ``jalert/``. Everything the user
varies - keywords, journals, window, thresholds - arrives through ``--spec`` or
the shortcut flags, so a run never touches a project's ``config.json``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from catalog import default_journals, load_catalog, resolve_journals  # noqa: E402
from jalert.fetch import collect_items  # noqa: E402
from jalert.score import Scorer, tier_of  # noqa: E402
from jalert.state import Store  # noqa: E402
from render import build_digest, build_markdown  # noqa: E402

TIER_RANK = {"must_read": 0, "worth_reading": 1, "other": 2}

DEFAULT_EXCLUDE_TERMS = [
    "retraction",
    "retracted",
    "correction",
    "corrigendum",
    "erratum",
    "author correction",
    "publisher correction",
    "editorial board",
    "in this issue",
    "issue information",
    "table of contents",
    "call for papers",
]
DEFAULT_EXCLUDE_DOI_PREFIXES = ["10.1038/d41586"]  # Nature news, not research

DEFAULT_TIERS = {"must_read": 12, "worth_reading": 6, "min_score": 3}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def slugify(text: str, fallback: str = "digest") -> str:
    text = (text or "").strip()
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text, flags=re.UNICODE).strip("-")
    return slug[:60] or fallback


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("jalert.skill")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    return logger


def normalize_keywords(raw) -> list[dict]:
    """Accept ``["air pollution", ...]``, ``[{"label":..,"terms":[..]}, ...]`` or a CSV string."""
    if raw in (None, "", [], ()):
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("[") or text.startswith("{"):
            try:  # allow a JSON array/object pasted straight on the command line
                raw = json.loads(text)
            except json.JSONDecodeError:
                pass
    if isinstance(raw, str):
        raw = [part.strip() for part in re.split(r"[,\n;，；]", raw) if part.strip()]
    if isinstance(raw, dict):
        raw = [raw]
    groups: list[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            label = (entry.get("label") or entry.get("term") or "").strip()
            terms = entry.get("terms") or ([entry["term"]] if entry.get("term") else [])
            terms = [str(t).strip().lower() for t in terms if str(t).strip()]
            if not label and terms:
                label = terms[0]
            if label and terms:
                groups.append({"label": label, "weight": int(entry.get("weight", 3)), "terms": terms})
        else:
            term = str(entry).strip()
            if term:
                groups.append({"label": term, "weight": 3, "terms": [term.lower()]})
    return groups


def sort_entries(entries: list[dict], tiers: dict, today: str) -> list[dict]:
    """Tier first, then score, then newest first (future-dated issues clamped)."""

    def key(entry):
        item = entry["item"]
        stamp = item.date or ""
        if stamp > today:
            stamp = today
        try:
            ordinal = -date.fromisoformat(stamp).toordinal()
        except ValueError:
            ordinal = 0
        return (
            TIER_RANK.get(tier_of(entry["scored"].score, tiers), 3),
            -entry["scored"].score,
            ordinal,
            item.journal,
        )

    return sorted(entries, key=key)


# --------------------------------------------------------------------------
# spec handling
# --------------------------------------------------------------------------


def load_spec(args) -> dict:
    spec: dict = {}
    if args.spec:
        path = Path(args.spec)
        if not path.is_file():
            raise SystemExit(f"spec not found: {path}")
        spec = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            raise SystemExit("spec must be a JSON object")

    spec.setdefault("topic", "文献日报")
    spec.setdefault("journals", None)
    spec.setdefault("keywords", [])
    spec.setdefault("days", 7)
    spec.setdefault("max_entries", 30)
    spec.setdefault("tiers", {})

    if args.keywords:
        spec["keywords"] = args.keywords
    if args.journals:
        spec["journals"] = [p.strip() for p in re.split(r"[,\n;，；]", args.journals) if p.strip()]
    if args.topic:
        spec["topic"] = args.topic
    if args.days:
        spec["days"] = args.days
    if args.max_entries is not None:
        spec["max_entries"] = args.max_entries
    return spec


def build_cfg(spec: dict, journals: list[dict], args) -> dict:
    tiers = dict(DEFAULT_TIERS)
    tiers.update({k: v for k, v in (spec.get("tiers") or {}).items() if k in DEFAULT_TIERS})

    sources = {"rss": True, "openalex": True, "crossref": True}
    if spec.get("sources"):
        sources.update(spec["sources"])
    if args.sources:
        chosen = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
        sources = {name: name in chosen for name in ("rss", "openalex", "crossref")}

    out_dir = Path(args.out_dir).resolve()
    return {
        "_root": str(out_dir),
        "project": {"name": spec["topic"]},
        "window": {
            "days": int(spec["days"]),
            "max_catchup_days": 365,
            "max_items_per_journal": 60,
            "workers": max(1, min(6, len(journals))),
            "rss_timeout_seconds": 25,
            "api_timeout_seconds": 45,
            "retries": 2,
            "sources": sources,
        },
        "output": {
            "dir": str(out_dir),
            "keep_days": 0,
            "max_entries": int(spec["max_entries"]),
            "open_after_run": False,
            "write_json_snapshot": True,
        },
        "keywords": spec["keywords"],
        "exclude_terms": spec.get("exclude_terms") or DEFAULT_EXCLUDE_TERMS,
        "exclude_doi_prefixes": spec.get("exclude_doi_prefixes") or DEFAULT_EXCLUDE_DOI_PREFIXES,
        "tiers": tiers,
        "journals": journals,
        "log": {"dir": str(out_dir / "logs"), "level": args.log_level},
        "reports_dir": str(out_dir),
        "log_dir": str(out_dir / "logs"),
        "state_db": str(out_dir / "state" / "seen.sqlite"),
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


PROFILES_PATH = SCRIPT_DIR / "profiles.json"


def load_profiles(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or PROFILES_PATH).read_text(encoding="utf-8"))


def apply_profile(spec: dict, profile_name: str | None, args) -> str:
    """Fill ``spec`` from a named keyword profile. Returns the profile used (or "")."""
    profiles = load_profiles(getattr(args, "profiles", None))
    name = profile_name or profiles.get("default_profile") or ""
    profile = (profiles.get("profiles") or {}).get(name)
    if not profile:
        return ""
    if not spec.get("keywords"):
        spec["keywords"] = profile.get("keywords", [])
    if profile.get("title") and spec.get("topic") in (None, "", "文献日报"):
        spec["topic"] = profile["title"]
    return name


def cmd_list_profiles() -> int:
    data = load_profiles()
    marker = data.get("default_profile")
    print("预置关键词方案（不给 --keywords / --spec 时用默认方案）\n")
    for key, profile in (data.get("profiles") or {}).items():
        star = "★" if key == marker else " "
        labels = " / ".join(k.get("label", "") for k in profile.get("keywords", []))
        print(f"{star} {key:<14} {profile.get('title',''):<20} {labels}")
    print('\n用法：--profile atmospheric ｜ 或直接 --keywords "your terms"')
    return 0


def cmd_list_journals() -> int:
    catalog = load_catalog()
    defaults = {j["name"] for j in default_journals(catalog)}
    print(f"期刊目录（共 {len(catalog['journals'])} 本，★ = 默认集合）\n")
    print(f"{'':2} {'名称':<48} {'ISSN':<10} {'RSS':<4} 别名")
    for entry in catalog["journals"]:
        star = "★" if entry["name"] in defaults else " "
        feed = "有" if entry.get("rss") else "—"
        aliases = ", ".join(entry.get("aliases") or [])
        print(f"{star:2} {entry['name']:<48} {entry.get('issn',''):<10} {feed:<4} {aliases}")
    print("\n用法：--journals \"Nature,ACP,1748-9326\"  或  --journals all / default")
    return 0


def cmd_check(cfg: dict, log, since_days: int) -> int:
    items, statuses = collect_items(cfg, log, since_days=since_days)
    print(f"\n{'期刊':<48} {'源':<9} {'状态':<5} {'条数':>5}  说明")
    for status in statuses:
        print(
            f"{status['journal']:<48} {status['source']:<9} "
            f"{'OK' if status['ok'] else 'FAIL':<5} {status['items']:>5}  {status.get('note', '')}"
        )
    failed = [s for s in statuses if not s["ok"]]
    print(f"\n抓取 {len(items)} 篇；{len(failed)} 个数据源失败（海外 API 偶发超时属正常）。")
    return 0


def run(args) -> int:
    if args.list_journals:
        return cmd_list_journals()
    if args.list_profiles:
        return cmd_list_profiles()

    if args.mailto:
        os.environ["JALERT_MAILTO"] = args.mailto

    spec = load_spec(args)
    used_profile = apply_profile(spec, args.profile, args)
    keywords = normalize_keywords(spec["keywords"])
    if not keywords:
        raise SystemExit(
            "没有关键词。用 --keywords \"air pollution, ozone\"、--profile atmospheric "
            "或 --spec spec.json 传入；中文关键词请先展开成英文词表（见 SKILL.md 第 1 步）。"
        )
    spec["keywords"] = keywords
    if used_profile:
        print(f"（关键词方案：{used_profile}）", file=sys.stderr)

    catalog = load_catalog(args.catalog)
    journals, unresolved = resolve_journals(spec.get("journals"), catalog)
    if unresolved:
        print(
            "⚠️ 以下期刊未在目录里找到，已跳过：" + "、".join(unresolved) + "\n"
            "   → 用 --list-journals 看现有条目，或在 spec 里用 "
            '{"name": "...", "issn": "1234-5678"} 直接给出 ISSN。',
            file=sys.stderr,
        )
    if not journals:
        raise SystemExit("没有可抓取的期刊。")

    cfg = build_cfg(spec, journals, args)
    log = setup_logging(args.log_level)
    out_dir = Path(cfg["reports_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.check:
        return cmd_check(cfg, log, int(spec["days"]))

    day = args.date or date.today().isoformat()
    tiers = cfg["tiers"]
    topic = spec["topic"]

    log.info("topic=%r journals=%d keywords=%d window=%d d",
             topic, len(journals), len(keywords), int(spec["days"]))
    items, statuses = collect_items(cfg, log, since_days=int(spec["days"]))
    failures = [s for s in statuses if not s["ok"]]

    scorer = Scorer(cfg["keywords"], cfg["exclude_terms"], cfg["exclude_doi_prefixes"])
    min_score = int(tiers["min_score"])
    matched = []
    for item in items:
        scored = scorer.score(item)
        if scored.excluded or scored.score < min_score:
            continue
        matched.append({"item": item, "scored": scored})
    log.info("keyword matched %d/%d items (min_score=%d)", len(matched), len(items), min_score)

    new_count: int | None = None
    seen_before = 0
    listed = matched
    if args.dedupe:
        with Store(cfg["state_db"]) as store:
            uids = [entry["item"].uid for entry in matched]
            known = store.known_uids(uids)
            fresh = [entry for entry in matched if entry["item"].uid not in known]
            new_count, seen_before = len(fresh), len(known)
            if not args.dry_run:
                store.save([(e["item"], e["scored"]) for e in fresh])
                store.record_run(
                    started=datetime.now().isoformat(timespec="seconds"),
                    fetched=len(items),
                    matched=len(matched),
                    new_items=len(fresh),
                    pushed=0,
                    report_path="",
                    note=f"skill run; {len(failures)} source failure(s)",
                )
            listed = fresh
            log.info("ledger: %d new, %d already seen", new_count, seen_before)

    ordered = sort_entries(listed, tiers, day)
    cap = int(spec["max_entries"])
    entries = ordered[:cap] if cap > 0 else ordered
    if len(ordered) > len(entries):
        log.info("listed top %d of %d matched entries (--max-entries)", len(entries), len(ordered))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    keyword_labels = " / ".join(k["label"] for k in keywords)
    markdown = build_markdown(
        topic=topic,
        day=day,
        entries=entries,
        statuses=statuses,
        fetched_total=len(items),
        matched_total=len(matched),
        journals_count=len(journals),
        window_days=int(spec["days"]),
        keyword_labels=keyword_labels,
        tiers=tiers,
        generated_at=stamp,
        new_count=new_count,
        seen_before=seen_before,
        source_failures=len(failures),
        all_entries=ordered,
    )

    slug = slugify(topic)
    md_path = Path(args.out) if args.out else (out_dir / f"{day}_{slug}.md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = md_path.with_suffix(".json")

    if not args.dry_run:
        md_path.write_text(markdown, encoding="utf-8")
        if not args.no_json:
            json_path.write_text(
                json.dumps(
                    {
                        "topic": topic,
                        "date": day,
                        "generated": stamp,
                        "journals": [j["name"] for j in journals],
                        "keywords": keywords,
                        "window_days": int(spec["days"]),
                        "fetched": len(items),
                        "matched": len(matched),
                        "listed": len(entries),
                        "tier_counts": {
                            tier: sum(1 for e in ordered if tier_of(e["scored"].score, tiers) == tier)
                            for tier in ("must_read", "worth_reading", "other")
                        },
                        "statuses": statuses,
                        "entries": [
                            {
                                "title": e["item"].title,
                                "journal": e["item"].journal,
                                "date": e["item"].date,
                                "doi": e["item"].doi,
                                "url": e["item"].url,
                                "score": e["scored"].score,
                                "labels": e["scored"].labels,
                                "abstract": e["item"].abstract,
                            }
                            for e in entries
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    if args.digest:
        _title, body = build_digest(
            topic=topic,
            day=day,
            entries=entries,
            fetched_total=len(items),
            matched_total=len(matched),
            tiers=tiers,
            max_items=int(spec.get("digest_max_items", 8)),
            report_ref="" if args.dry_run else str(md_path),
        )
        print("\n" + body)
    if args.print_report or args.dry_run:
        print("\n" + markdown)

    if not args.dry_run:
        print(f"\n报告：{md_path}" + ("" if args.no_json else f"\n结构化：{json_path}"))
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="digest.py",
        description="按关键词抓取指定期刊的近期文献，生成 Markdown 日报。",
    )
    parser.add_argument("--spec", help="JSON 任务描述文件（见 SKILL.md）")
    parser.add_argument("--keywords", help='逗号分隔关键词，如 "air pollution, ozone, pm2.5"')
    parser.add_argument("--profile", help="用预置关键词方案，如 atmospheric / microplastic / carbon / ai-earth")
    parser.add_argument("--profiles", help="自定义方案文件（默认内置 profiles.json）")
    parser.add_argument("--list-profiles", action="store_true", help="打印预置关键词方案后退出")
    parser.add_argument("--journals", help='逗号分隔期刊名/别名/ISSN；或 "default" / "all"')
    parser.add_argument("--topic", help="报告标题（默认取自 spec，否则「文献日报」）")
    parser.add_argument("--days", type=int, help="时间窗天数（默认 7）")
    parser.add_argument("--max-entries", type=int, help="报告最多列出多少条（默认 30，0 = 不限制）")
    parser.add_argument("--sources", help="逗号分隔：rss,openalex,crossref")
    parser.add_argument("--out", help="Markdown 输出路径（默认 <out-dir>/<日期>_<主题>.md）")
    parser.add_argument("--out-dir", default="journal-digest", help="输出目录（默认 ./journal-digest）")
    parser.add_argument("--catalog", help="自定义期刊目录 JSON（默认内置 journals.json）")
    parser.add_argument("--dedupe", action="store_true", help="启用跨天去重台账（默认关闭，每次都看全量命中）")
    parser.add_argument("--mailto", help="留在 OpenAlex/Crossref 的联系邮箱（走礼貌池，更快更稳）")
    parser.add_argument("--date", help="报告日期标签 YYYY-MM-DD（默认今天）")
    parser.add_argument("--print", dest="print_report", action="store_true", help="把完整报告打到 stdout")
    parser.add_argument("--digest", action="store_true", help="额外输出适合聊天/IM 的短版摘要")
    parser.add_argument("--dry-run", action="store_true", help="不写文件，只打印")
    parser.add_argument("--no-json", action="store_true", help="不写结构化 JSON")
    parser.add_argument("--check", action="store_true", help="只测数据源连通性，不出报告")
    parser.add_argument("--list-journals", action="store_true", help="打印内置期刊目录后退出")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
