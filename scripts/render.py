"""Markdown rendering for the journal-alert skill.

Two outputs:

* :func:`build_markdown` - the full digest, saved as ``<day>_<slug>.md``.
* :func:`build_digest`   - a short, one-screen summary for chat/IM delivery.

Adapted from the journal-alert project's ``jalert/report.py``; the wording here
describes a point-in-time *snapshot* (no cross-day ledger) unless the caller
passes ``new_count``.
"""

from __future__ import annotations

from datetime import date as _date

from jalert.score import TIER_TITLES, tier_of

TIER_ORDER = ["must_read", "worth_reading", "other"]


def _fmt_date(value: str) -> str:
    """Elsevier-style feeds stamp the *issue* date, which can be in the future."""
    if not value:
        return "未知"
    return f"{value}（在线预发表）" if value > _date.today().isoformat() else value


def _link(item) -> str:
    if getattr(item, "url", ""):
        return item.url
    if getattr(item, "doi", ""):
        return f"https://doi.org/{item.doi}"
    return ""


def _doi_link(doi: str) -> str:
    return f"[{doi}](https://doi.org/{doi})" if doi else "—"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


def _tier_counts(entries: list[dict], tiers: dict) -> dict:
    counts = {tier: 0 for tier in TIER_ORDER}
    for entry in entries:
        counts[tier_of(entry["scored"].score, tiers)] += 1
    return counts


def build_markdown(
    *,
    topic: str,
    day: str,
    entries: list[dict],
    statuses: list[dict],
    fetched_total: int,
    matched_total: int,
    journals_count: int,
    window_days: int,
    keyword_labels: str,
    tiers: dict,
    generated_at: str,
    new_count: int | None = None,
    seen_before: int = 0,
    source_failures: int = 0,
    all_entries: list[dict] | None = None,
) -> str:
    # Tier counts describe the whole matched set, never just the rows we were
    # told to list - otherwise a capped report claims "必读 20 / 0 / 0" while the
    # header says 132 matched.
    counted = all_entries if all_entries is not None else entries
    counts = _tier_counts(counted, tiers)
    capped = all_entries is not None and len(all_entries) > len(entries)
    lines: list[str] = []
    lines.append(f"# {topic} · {day}")
    lines.append("")
    lines.append(
        f"> 期刊 **{journals_count}** 本 ｜ 时间窗 近 **{window_days}** 天 ｜ "
        f"抓取 **{fetched_total}** 篇 ｜ 关键词命中 **{matched_total}** 篇"
    )
    if new_count is not None:
        lines.append(
            f"> 其中本次新增 **{new_count}** 篇（{seen_before} 篇此前已读过，未重复列出）"
        )
    lines.append(
        f"> 必读 **{counts['must_read']}** ｜ 值得一读 **{counts['worth_reading']}** ｜ "
        f"其他相关 **{counts['other']}**" + ("（按全部命中统计）" if capped else "")
    )
    if capped:
        lines.append(
            f"> 命中 **{len(all_entries)}** 篇，按重要度只列出前 **{len(entries)}** 篇"
            f"（调大 `--max-entries` 可看全）"
        )
    if keyword_labels:
        lines.append(f"> 关注方向：{keyword_labels}")
    lines.append(f"> 生成时间：{generated_at}")
    lines.append("")

    if not entries:
        lines.append("## 本次无命中")
        lines.append("")
        lines.append("抓取到的文献里没有同时满足关键词与时间窗条件的条目。")
        lines.append("可尝试：放宽时间窗（`--days 14`）、增补同义词 / 英文写法、或换几本期刊。")
        lines.append("")
    for tier in TIER_ORDER:
        bucket = [e for e in entries if tier_of(e["scored"].score, tiers) == tier]
        if not bucket:
            continue
        lines.append(f"## {TIER_TITLES[tier]}（{len(bucket)}）")
        lines.append("")
        for index, entry in enumerate(bucket, 1):
            item = entry["item"]
            scored = entry["scored"]
            url = _link(item)
            heading = f"[{item.title}]({url})" if url else item.title
            lines.append(f"### {index}. {heading}")
            lines.append("")
            meta = [f"**期刊**：{item.journal}", f"**日期**：{_fmt_date(item.date)}"]
            if item.doi:
                meta.append(f"**DOI**：{_doi_link(item.doi)}")
            lines.append("- " + " ｜ ".join(meta))
            hits = "、".join(
                f"{m.label}（{'标题' if m.field_name == 'title' else '摘要'}：{m.term}）"
                for m in scored.matches
            )
            lines.append(f"- **匹配**：{hits} ｜ **得分**：{scored.score}")
            if getattr(item, "authors", None):
                authors = ", ".join(item.authors[:6])
                lines.append(f"- **作者**：{authors}{' 等' if len(item.authors) > 6 else ''}")
            if item.abstract:
                lines.append("")
                lines.append(f"> {_truncate(item.abstract, 700)}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 数据源状态")
    lines.append("")
    lines.append("| 期刊 | 数据源 | 状态 | 条数 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for status in statuses:
        mark = "✅" if status["ok"] else "❌"
        note = (status.get("note") or "").replace("|", "/")
        lines.append(
            f"| {status['journal']} | {status['source']} | {mark} | {status['items']} | {note} |"
        )
    lines.append("")
    if source_failures:
        lines.append(
            f"⚠️ 有 {source_failures} 个数据源本次抓取失败（原因见上表）；"
            "失败不影响其他来源，海外站点偶发超时属正常现象。"
        )
    else:
        lines.append("✅ 全部数据源抓取正常。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*由 journal-alert skill 生成 · 数据源：期刊 RSS / OpenAlex / Crossref*")
    lines.append("")
    return "\n".join(lines)


def build_digest(
    *,
    topic: str,
    day: str,
    entries: list[dict],
    fetched_total: int,
    matched_total: int,
    tiers: dict,
    max_items: int = 10,
    max_chars: int = 1800,
    report_ref: str = "",
) -> tuple[str, str]:
    """Return ``(title, plain_text_body)`` for a chat / IM push."""
    must = [e for e in entries if tier_of(e["scored"].score, tiers) == "must_read"]
    must_ids = {id(e) for e in must}
    rest = [e for e in entries if id(e) not in must_ids]
    title = f"{topic} {day}：命中 {len(entries)} 篇，必读 {len(must)} 篇"

    lines = [f"抓取 {fetched_total} 篇 · 命中 {matched_total} 篇 · 列出 {len(entries)} 篇", ""]
    shown = 0
    for index, entry in enumerate(must + rest, 1):
        if shown >= max_items:
            break
        item = entry["item"]
        url = _link(item)
        star = "🔥" if id(entry) in must_ids else "·"
        hits = "、".join(entry["scored"].labels)
        block = [
            f"{index}. {star} {_truncate(item.title, 110)}",
            f"　　{item.journal} · {item.date} · 匹配 {hits}",
        ]
        if url:
            block.append(f"　　{url}")
        # Drop whole entries rather than cutting one in half, but always keep at
        # least three so the message never comes back nearly empty.
        if len("\n".join(lines + block)) > max_chars and shown >= 3:
            break
        lines.extend(block)
        shown += 1
    if len(entries) > shown:
        lines.append("")
        lines.append(f"…… 其余 {len(entries) - shown} 篇见完整报告。")
    if report_ref:
        lines.append("")
        lines.append(f"完整报告：{report_ref}")

    return title, "\n".join(lines)
