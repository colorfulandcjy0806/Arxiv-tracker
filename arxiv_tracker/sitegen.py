# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import html
import os
from typing import Any, Dict, List, Optional

try:
    from markdown import markdown as _md
except Exception:
    _md = None


def _esc(value: Optional[str]) -> str:
    return html.escape(value or "", quote=True)


def _md2html(md: str) -> str:
    if not md:
        return ""
    if _md:
        return _md(md, extensions=["extra", "sane_lists", "tables"])
    return "<pre class='mono'>" + _esc(md) + "</pre>"


def _css(accent: str = "#2563eb") -> str:
    return f"""
:root {{
  --bg:#f8fafc;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#667085;
  --border:#e5e7eb;
  --soft:#f1f5f9;
  --acc:{accent};
}}
:root[data-theme="dark"] {{
  --bg:#0b0f17;
  --card:#111827;
  --text:#e5e7eb;
  --muted:#9ca3af;
  --border:#1f2937;
  --soft:#172033;
  --acc:{accent};
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;line-height:1.6}}
.container{{max-width:960px;margin:0 auto;padding:18px}}
.header{{display:flex;gap:10px;justify-content:space-between;align-items:center;margin:8px 0 16px;flex-wrap:wrap}}
h1{{font-size:22px;margin:0}}
.badge{{font-size:12px;color:#111827;background:var(--acc);padding:2px 8px;border-radius:999px}}
.track-section{{margin-top:22px}}
.track-heading{{background:var(--soft);border:1px solid var(--border);border-radius:14px;padding:12px 14px;margin-bottom:10px}}
.track-heading h2{{font-size:18px;margin:0}}
.track-heading p{{font-size:13px;color:var(--muted);margin:3px 0 0}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px 18px;margin:14px 0;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.title{{font-weight:700;margin:0 0 6px 0;font-size:18px}}
.meta-line{{color:var(--muted);font-size:13px;margin:2px 0}}
.track-badge{{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;background:var(--soft);border:1px solid var(--border);color:var(--muted);margin-bottom:7px}}
.links a{{color:var(--acc);text-decoration:none;margin-right:12px}}
.detail{{margin-top:10px;background:rgba(2,6,23,.03);border:1px solid var(--border);border-radius:10px;padding:8px 10px}}
summary{{cursor:pointer;color:var(--acc)}}
.mono{{white-space:pre-wrap;background:rgba(2,6,23,.03);border:1px solid var(--border);padding:10px;border-radius:10px}}
.row{{display:grid;grid-template-columns:1fr;gap:12px}}
.footer{{color:var(--muted);font-size:13px;margin:20px 0 10px}}
.hr{{height:1px;background:var(--border);margin:14px 0}}
.history-list a{{display:block;color:var(--acc);text-decoration:none;margin:4px 0}}
.controls{{display:flex;gap:8px;align-items:center}}
.btn{{border:1px solid var(--border);background:var(--card);padding:6px 10px;border-radius:10px;cursor:pointer;color:var(--text)}}
.btn:hover{{border-color:var(--acc)}}
.empty{{color:var(--muted);padding:18px 0}}
"""


def _join_links(item: Dict[str, Any]) -> str:
    parts: List[str] = []
    if item.get("html_url"):
        parts.append(f'<a href="{_esc(item["html_url"])}">Abs</a>')
    if item.get("pdf_url"):
        parts.append(f'<a href="{_esc(item["pdf_url"])}">PDF</a>')
    if item.get("code_urls"):
        for i, url in enumerate(item["code_urls"][:3]):
            parts.append(f'<a href="{_esc(url)}">Code{i + 1}</a>')
    if item.get("project_urls"):
        for i, url in enumerate(item["project_urls"][:2]):
            parts.append(f'<a href="{_esc(url)}">Project{i + 1}</a>')
    return " · ".join(parts)


def _card(
    item: Dict[str, Any],
    trans_zh: Optional[Dict[str, str]],
    sum_zh: Optional[Dict[str, str]],
    sum_en: Optional[Dict[str, str]],
) -> str:
    title = item.get("title") or ""
    authors = ", ".join(item.get("authors") or [])
    venue = item.get("venue_inferred") or (item.get("journal_ref") or "")
    published = item.get("published") or "—"
    updated = item.get("updated") or "—"
    comments = item.get("comments") or ""
    abstract = item.get("summary") or ""
    track = item.get("_track") or "core"

    zh_title = (trans_zh or {}).get("title_zh")
    zh_abstract = (trans_zh or {}).get("summary_zh")

    digest_en = (sum_en or {}).get("digest_en") or (sum_zh or {}).get("digest_en") or ""
    digest_zh = (sum_zh or {}).get("digest_zh") or (sum_en or {}).get("digest_zh") or ""

    track_name = "Social Event Detection" if track == "core" else "Related Research"

    parts = [
        '<div class="card">',
        f'<div class="track-badge">{_esc(track_name)}</div>',
        f'<div class="title">{_esc(title)}</div>',
        f'<div class="meta-line">Authors: {_esc(authors)}</div>',
    ]

    if venue:
        parts.append(f'<div class="meta-line">Venue: {_esc(venue)}</div>')

    parts.append(
        f'<div class="meta-line">First: {_esc(published)} · Latest: {_esc(updated)}</div>'
    )

    if comments:
        parts.append(f'<div class="meta-line">Comments: {_esc(comments)}</div>')

    links = _join_links(item)
    if links:
        parts.append(f'<div class="links" style="margin-top:8px">{links}</div>')

    if abstract:
        parts.append('<details class="detail"><summary>Abstract</summary>')
        parts.append(f'<div class="mono">{_esc(abstract)}</div></details>')

    if zh_abstract or zh_title:
        parts.append('<details class="detail"><summary>中文标题/摘要</summary>')
        if zh_title:
            parts.append(f'<div class="mono"><b>标题：</b>{_esc(zh_title)}</div>')
        if zh_abstract:
            parts.append(
                f'<div class="mono" style="margin-top:8px">{_esc(zh_abstract)}</div>'
            )
        parts.append("</details>")

    if digest_en or digest_zh:
        parts.append('<details class="detail"><summary>Summary / 总结</summary>')
        if digest_en:
            parts.append(f'<div class="mono">{_esc(digest_en)}</div>')
        if digest_zh:
            parts.append(
                f'<div class="mono" style="margin-top:8px">{_esc(digest_zh)}</div>'
            )
        parts.append("</details>")

    parts.append("</div>")
    return "\n".join(parts)


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _history_list(archive_dir: str, keep: int) -> List[str]:
    if not os.path.isdir(archive_dir):
        return []

    files = [name for name in os.listdir(archive_dir) if name.endswith(".html")]
    files.sort(reverse=True)
    files = files[:keep]

    return [
        f'<a href="archive/{_esc(name)}">{_esc(name.replace(".html", ""))}</a>'
        for name in files
    ]


def _render_track_section(
    heading: str,
    description: str,
    cards: List[str],
) -> str:
    if not cards:
        return ""

    return "\n".join(
        [
            '<section class="track-section">',
            '<div class="track-heading">',
            f"<h2>{_esc(heading)} ({len(cards)})</h2>",
            f"<p>{_esc(description)}</p>",
            "</div>",
            '<div class="row">',
            "\n".join(cards),
            "</div>",
            "</section>",
        ]
    )


def _build_page(
    title: str,
    sub: str,
    content_html: str,
    history_html: str,
    theme_mode: str,
    accent: str,
) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    js = f"""
<script>
(function() {{
  const root = document.documentElement;
  function apply(t) {{
    if (t === 'dark') root.setAttribute('data-theme', 'dark');
    else if (t === 'light') root.removeAttribute('data-theme');
    else {{
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
        root.setAttribute('data-theme', 'dark');
      else root.removeAttribute('data-theme');
    }}
  }}
  let t = localStorage.getItem('theme') || '{theme_mode}';
  if (!['light', 'dark', 'auto'].includes(t)) t = 'light';
  apply(t);

  window.__toggleTheme = function() {{
    let cur = localStorage.getItem('theme') || '{theme_mode}';
    if (cur === 'light') cur = 'dark';
    else if (cur === 'dark') cur = 'auto';
    else cur = 'light';
    localStorage.setItem('theme', cur);
    apply(cur);
    const el = document.getElementById('theme-label');
    if (el) el.textContent = cur.toUpperCase();
  }};

  window.__expandAll = function(open) {{
    document.querySelectorAll('details').forEach(d => d.open = !!open);
  }};
}})();
</script>
"""

    controls = """
<div class="controls">
  <button class="btn" onclick="__toggleTheme()">Theme: <span id="theme-label" style="margin-left:6px">AUTO</span></button>
  <button class="btn" onclick="__expandAll(true)">Expand All</button>
  <button class="btn" onclick="__expandAll(false)">Collapse All</button>
</div>
"""

    if not content_html:
        content_html = '<div class="empty">今日暂无新增论文。</div>'

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_esc(title)}</title>
  <style>{_css(accent)}</style>
  {js}
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{_esc(title)}</h1>
      <div style="display:flex;gap:10px;align-items:center">
        {controls}
        <span class="badge">{_esc(now)}</span>
      </div>
    </div>
    <div class="hr"></div>
    <div>{_esc(sub)}</div>
    {content_html}
    <details style="margin-top:16px" class="detail">
      <summary>History</summary>
      <div class="history-list">{history_html}</div>
    </details>
    <div class="footer">Generated by arxiv-tracker</div>
  </div>
</body>
</html>
"""


def generate_site(
    items: List[Dict[str, Any]],
    summaries_zh: Dict[str, Dict[str, str]],
    summaries_en: Dict[str, Dict[str, str]],
    translations: Dict[str, Dict[str, str]],
    site_dir: str,
    site_title: str = "arXiv Results",
    keep_runs: int = 60,
    theme: str = "light",
    accent: Optional[str] = None,
) -> Dict[str, str]:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    archive_dir = os.path.join(site_dir, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    open(os.path.join(site_dir, ".nojekyll"), "w").close()

    core_cards: List[str] = []
    related_cards: List[str] = []

    for item in items:
        sid = item.get("id") or ""
        card = _card(
            item,
            translations.get(sid),
            summaries_zh.get(sid),
            summaries_en.get(sid),
        )
        if (item.get("_track") or "core") == "related":
            related_cards.append(card)
        else:
            core_cards.append(card)

    sections = []
    sections.append(
        _render_track_section(
            "🔥 Social Event Detection",
            "核心研究方向：社交媒体事件检测、发现、聚类、增量检测与事件演化。",
            core_cards,
        )
    )
    sections.append(
        _render_track_section(
            "💡 Related Research",
            "可迁移方法：事件抽取/发现、多模态事件、动态图、在线聚类、LLM/RAG 等。",
            related_cards,
        )
    )
    content_html = "\n".join(section for section in sections if section)

    history_html = "\n".join(_history_list(archive_dir, keep_runs))
    acc = (accent or "#2563eb").strip()

    archive_html = _build_page(
        site_title,
        f"Snapshot: {stamp}",
        content_html,
        history_html,
        theme_mode=theme,
        accent=acc,
    )
    archive_path = os.path.join(archive_dir, f"{stamp}.html")
    _write(archive_path, archive_html)

    index_html = _build_page(
        site_title,
        "Latest digest",
        content_html,
        history_html,
        theme_mode=theme,
        accent=acc,
    )
    index_path = os.path.join(site_dir, "index.html")
    _write(index_path, index_html)

    return {
        "index_path": index_path,
        "archive_path": archive_path,
        "stamp": stamp,
    }
