# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Optional

# Search title + abstract only. This avoids comment-field noise and keeps the
# arXiv query compact enough to avoid oversized URLs / HTTP 400 errors.
FIELDS = ("ti", "abs")


def _quote(term: str) -> str:
    """Quote multi-word phrases for the arXiv query language."""
    text = (term or "").strip()
    if not text:
        return ""
    if re.search(r"\s", text):
        return f'"{text}"'
    return text


def _field_group(term: str) -> str:
    """Search one term in title OR abstract."""
    q = _quote(term)
    if not q:
        return ""
    return "(" + " OR ".join(f"{field}:{q}" for field in FIELDS) + ")"


def _category_group(categories: List[str]) -> str:
    cats = [c.strip() for c in (categories or []) if c and c.strip()]
    if not cats:
        return ""
    return "(" + " OR ".join(f"cat:{c}" for c in cats) + ")"


def _keywords_group(keywords: List[str]) -> str:
    groups = [_field_group(k) for k in (keywords or []) if k and k.strip()]
    groups = [g for g in groups if g]
    if not groups:
        return ""
    return "(" + " OR ".join(groups) + ")"


def _exclude_suffix(exclude_keywords: Optional[List[str]]) -> str:
    """arXiv uses ANDNOT for boolean exclusion."""
    group = _keywords_group(exclude_keywords or [])
    if not group:
        return ""
    return f" ANDNOT {group}"


def build_search_query(
    categories: List[str],
    keywords: List[str],
    exclude_keywords: Optional[List[str]] = None,
    logic: str = "AND",
) -> str:
    """Build the strict Core / Social Event Detection query."""
    cat_q = _category_group(categories)
    key_q = _keywords_group(keywords)

    if cat_q and key_q:
        op = "AND" if (logic or "AND").upper() == "AND" else "OR"
        positive = f"({cat_q} {op} {key_q})"
    elif cat_q:
        positive = cat_q
    elif key_q:
        positive = key_q
    else:
        positive = "all:*"

    return positive + _exclude_suffix(exclude_keywords)


def build_related_search_query(
    categories: List[str],
    direct_keywords: List[str],
    method_keywords: List[str],
    social_context_keywords: List[str],
    event_context_keywords: List[str],
    exclude_keywords: Optional[List[str]] = None,
) -> str:
    """
    Build the Related Research query.

    Structure:

        categories AND (
            direct_related_keywords
            OR
            (
                method_keywords
                AND social_media_context
                AND event_or_topic_context
            )
        )

    The extra context split is deliberate. A paper is not admitted merely
    because it says "LLM + event detection" or "GNN + social network".
    Broad methods must be tied to BOTH social-media data and event/topic work.
    """
    cat_q = _category_group(categories)
    direct_q = _keywords_group(direct_keywords)
    method_q = _keywords_group(method_keywords)
    social_q = _keywords_group(social_context_keywords)
    event_q = _keywords_group(event_context_keywords)

    parts: List[str] = []

    if direct_q:
        parts.append(direct_q)

    if method_q and social_q and event_q:
        parts.append(f"({method_q} AND {social_q} AND {event_q})")

    related_q = "(" + " OR ".join(parts) + ")" if parts else ""

    if cat_q and related_q:
        positive = f"({cat_q} AND {related_q})"
    elif related_q:
        positive = related_q
    elif cat_q:
        positive = cat_q
    else:
        positive = "all:*"

    return positive + _exclude_suffix(exclude_keywords)
