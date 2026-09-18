# -*- coding: utf-8 -*-
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

try:
    from markdown import markdown as _md
except Exception:
    _md = None


def _esc(x: Optional[str]) -> str:
    return html.escape(x or "", quote=True)


def _md2html(md: str) -> str:
    if not md:
        return ""
    if _md:
        return _md(md, extensions=["extra", "sane_lists", "tables"])
    return "<pre style='white-space:pre-wrap'>" + _esc(md) + "</pre>"


def _strip_redundant_links(md: str) -> str:
    out = []
    for line in (md or "").splitlines():
        if line.strip().lower().startswith("- **links**"):
            continue
        out.append(line)
    return "\n".join(out)


def _join_links(it: Dict[str, Any]) -> str:
    parts = []
    if it.get("html_url"):
        parts.append(f'<a href="{_esc(it["html_url"])}">Abs</a>')
    if it.get("pdf_url"):
        parts.append(f'<a href="{_esc(it["pdf_url"])}">PDF</a>')
    if it.get("code_urls"):
        links = [
            f'<a href="{_esc(url)}">Code{i + 1}</a>'
            for i, url in enumerate(it["code_urls"][:3])
        ]
        parts.append(" · ".join(links))
    if it.get("project_urls"):
        links = [
            f'<a href="{_esc(url)}">Project{i + 1}</a>'
            for i, url in enumerate(it["project_urls"][:2])
        ]
        parts.append(" · ".join(links))
    return " · ".join(parts)


CSS = """
.container{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#0f172a}
.digest-note{color:#667085;font-size:13px;margin:0 0 14px 0}
.track-header{margin:22px 0 8px 0;padding:10px 12px;border-radius:12px;background:#f1f5f9;border:1px solid #e2e8f0}
.track-header h3{margin:0;font-size:17px}
.track-header p{margin:3px 0 0 0;color:#667085;font-size:13px}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:14px;margin:12px 0;background:#fff}
.title{font-weight:700;font-size:16px;margin:0 0 6px 0}
.title a{color:#0f172a;text-decoration:none}
.meta{color:#667085;font-size:13px;margin:2px 0}
.track-badge{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;background:#e2e8f0;color:#334155;margin-bottom:7px}
.links a{color:#2563eb;text-decoration:none;margin-right:10px}
.grid{display:grid;grid-template-columns:1fr;gap:10px}
@media (min-width:860px){.grid-2{grid-template-columns:1fr 1fr}}
.section{border:1px solid #eef2f7;border-radius:10px;padding:8px 10px;background:#f8fafc;margin-top:8px}
.section h4{margin:4px 0 6px 0;font-size:14px}
"""


def _render_card(
    it: Dict[str, Any],
    t_zh: Optional[Dict[str, str]] = None,
    sum_zh: Optional[Dict[str, str]] = None,
    sum_en: Optional[Dict[str, str]] = None,
    detail: str = "full",
) -> str:
    title = it.get("title") or ""
    title_link = it.get("html_url") or "#"
    authors = ", ".join(it.get("authors", []))
    venue = it.get("venue_inferred") or (it.get("journal_ref") or "")
    pub = it.get("published") or "—"
    upd = it.get("updated") or "—"
    comments = it.get("comments") or ""
    summary = it.get("summary") or ""
    track = it.get("_track") or "core"

    zh_title = (t_zh or {}).get("title_zh")
    zh_sum = (t_zh or {}).get("summary_zh")

    digest_en = (sum_en or {}).get("digest_en") or (sum_zh or {}).get("digest_en") or ""
    digest_zh = (sum_zh or {}).get("digest_zh") or (sum_en or {}).get("digest_zh") or ""

    badge = "Social Event Detection" if track == "core" else "Related Research"

    out = ['<div class="card">']
    out.append(f'<div class="track-badge">{_esc(badge)}</div>')
    out.append(f'<div class="title"><a href="{_esc(title_link)}">{_esc(title)}</a></div>')
    out.append(f'<div class="meta">Authors: {_esc(authors)}</div>')
    if venue:
        out.append(f'<div class="meta">Venue: {_esc(venue)}</div>')
    out.append(f'<div class="meta">First: {_esc(pub)} · Latest: {_esc(upd)}</div>')
    if comments:
        out.append(f'<div class="meta">Comments: {_esc(comments)}</div>')

    links = _join_links(it)
    if links:
        out.append(f'<div class="links" style="margin:8px 0">{links}</div>')

    if detail == "full" and summary:
        out.append(
            '<div class="section"><h4>Abstract</h4><div style="white-space:pre-wrap">'
            + _esc(summary)
            + "</div></div>"
        )

    if zh_title or (detail == "full" and zh_sum):
        zh_parts = []
        if zh_title:
            zh_parts.append(f"<p><b>标题：</b>{_esc(zh_title)}</p>")
        if detail == "full" and zh_sum:
            zh_parts.append("<div style='white-space:pre-wrap'>" + _esc(zh_sum) + "</div>")
        out.append('<div class="section"><h4>中文标题/摘要</h4>' + "".join(zh_parts) + "</div>")

    if digest_en or digest_zh:
        inner = ""
        if digest_en:
            inner += "<div style='white-space:pre-wrap'>" + _esc(digest_en) + "</div>"
        if digest_zh:
            inner += (
                "<div style='white-space:pre-wrap;margin-top:8px'>"
                + _esc(digest_zh)
                + "</div>"
            )
        out.append('<div class="section"><h4>Summary / 总结</h4>' + inner + "</div>")

    out.append("</div>")
    return "\n".join(out)


def _render_track(
    heading: str,
    description: str,
    items: List[Dict[str, Any]],
    translations: Dict[str, Dict[str, str]],
    summaries_zh: Dict[str, Dict[str, str]],
    summaries_en: Dict[str, Dict[str, str]],
    detail: str,
) -> str:
    if not items:
        return ""

    body = [
        '<div class="track-header">',
        f"<h3>{_esc(heading)} ({len(items)})</h3>",
        f"<p>{_esc(description)}</p>",
        "</div>",
    ]

    for it in items:
        sid = it.get("id") or ""
        body.append(
            _render_card(
                it,
                translations.get(sid),
                summaries_zh.get(sid),
                summaries_en.get(sid),
                detail=detail,
            )
        )
    return "\n".join(body)


def render_email_html(
    items: List[Dict[str, Any]],
    lang: str = "both",
    translations: Optional[Dict[str, Dict[str, str]]] = None,
    summaries_zh: Optional[Dict[str, Dict[str, str]]] = None,
    summaries_en: Optional[Dict[str, Dict[str, str]]] = None,
    detail: str = "full",
    max_items: int = 50,
    title: str = "arXiv Daily Digest",
) -> str:
    translations = translations or {}
    summaries_zh = summaries_zh or {}
    summaries_en = summaries_en or {}

    head = f"""
    <meta charset="utf-8">
    <div class="container">
      <h2 style="margin:8px 0 6px 0;">{_esc(title)}</h2>
      <p class="digest-note">核心方向优先：Social Event Detection；同时补充少量可迁移的方法与相关事件研究。</p>
      <style>{CSS}</style>
    """

    if not items:
        return head + "<p>No results.</p></div>"

    selected = items[:max_items]
    core_items = [it for it in selected if (it.get("_track") or "core") == "core"]
    related_items = [it for it in selected if it.get("_track") == "related"]

    # Backward compatibility: old items without _track are treated as core.
    body = [head]
    body.append(
        _render_track(
            "🔥 Social Event Detection",
            "与你的核心研究方向直接相关的论文。",
            core_items,
            translations,
            summaries_zh,
            summaries_en,
            detail,
        )
    )
    body.append(
        _render_track(
            "💡 Related Research",
            "事件抽取、事件发现、多模态事件、动态图、在线聚类、LLM/RAG 等可借鉴方向。",
            related_items,
            translations,
            summaries_zh,
            summaries_en,
            detail,
        )
    )
    body.append("</div>")
    return "\n".join(part for part in body if part)
