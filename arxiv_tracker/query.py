# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Optional

# Search title + abstract only.  This keeps arXiv queries compact and relevant.
# The previous version also searched comments and generated space/hyphen variants,
# which made the query string several kilobytes long.
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
    """
    arXiv's documented boolean exclusion operator is ANDNOT (not "AND NOT").
    """
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
    """
    Build the Core / Social Event Detection query.

    categories are OR-ed together.
    keywords are OR-ed together.
    logic controls how the two groups are connected.
    """
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
    context_keywords: List[str],
    exclude_keywords: Optional[List[str]] = None,
) -> str:
    """
    Build the Related Research query.

    Structure:

        categories AND (
            direct_related_keywords
            OR
            (method_keywords AND context_keywords)
        )

    Broad methods such as LLM/RAG/GNN are therefore not searched alone.
    They must occur together with an event/social-media context term.
    """
    cat_q = _category_group(categories)
    direct_q = _keywords_group(direct_keywords)
    method_q = _keywords_group(method_keywords)
    context_q = _keywords_group(context_keywords)

    parts: List[str] = []
    if direct_q:
        parts.append(direct_q)
    if method_q and context_q:
        parts.append(f"({method_q} AND {context_q})")

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
