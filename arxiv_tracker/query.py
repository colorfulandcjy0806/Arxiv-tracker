# arxiv_tracker/query.py
from __future__ import annotations

import re
from typing import List, Optional


FIELDS = ("ti", "abs", "co")  # title / abstract / comments


def _quote(term: str) -> str:
    """Quote phrases containing whitespace or hyphens."""
    t = (term or "").strip()
    if re.search(r"[\s-]", t):
        return f'"{t}"'
    return t


def _field_or(fields: List[str], term: str) -> str:
    q = _quote(term)
    return "(" + " OR ".join(f"{field}:{q}" for field in fields) + ")"


def _expand_variants(keyword: str) -> List[str]:
    """Generate space/hyphen variants for a keyword phrase."""
    k = (keyword or "").strip()
    if not k:
        return []

    out = {k}
    if " " in k:
        out.add(k.replace(" ", "-"))
    if "-" in k:
        out.add(k.replace("-", " "))
    return sorted(out, key=len, reverse=True)


def _kw_group(keyword: str) -> str:
    """Build a title/abstract/comments query group for one logical keyword."""
    variants = _expand_variants(keyword)
    parts = [_field_or(list(FIELDS), variant) for variant in variants]

    # Preserve the project's old open-vocabulary special handling.
    low = (keyword or "").lower()
    if ("open vocabulary" in low or "open-vocabulary" in low) and "segmentation" in low:
        ov_terms = [
            "open vocabulary",
            "open-vocabulary",
            "open-vocabulary segmentation",
            "open vocabulary segmentation",
        ]
        seg_terms = ["segmentation", "image segmentation"]
        ov_or = "(" + " OR ".join(_field_or(list(FIELDS), term) for term in ov_terms) + ")"
        seg_or = "(" + " OR ".join(_field_or(list(FIELDS), term) for term in seg_terms) + ")"
        parts.append(f"({ov_or} AND {seg_or})")

    return "(" + " OR ".join(parts) + ")" if parts else ""


def _category_group(categories: List[str]) -> str:
    cats = [c.strip() for c in (categories or []) if c and c.strip()]
    if not cats:
        return ""
    return "(" + " OR ".join(f"cat:{c}" for c in cats) + ")"


def _keywords_group(keywords: List[str]) -> str:
    keys = [k.strip() for k in (keywords or []) if k and k.strip()]
    groups = [_kw_group(k) for k in keys]
    groups = [g for g in groups if g]
    if not groups:
        return ""
    return "(" + " OR ".join(groups) + ")"


def _exclude_group(exclude_keywords: Optional[List[str]]) -> str:
    excs = [e.strip() for e in (exclude_keywords or []) if e and e.strip()]
    groups = [_kw_group(e) for e in excs]
    groups = [g for g in groups if g]
    if not groups:
        return ""
    return " AND NOT (" + " OR ".join(groups) + ")"


def build_search_query(
    categories: List[str],
    keywords: List[str],
    exclude_keywords: Optional[List[str]] = None,
    logic: str = "AND",
) -> str:
    """
    Build the normal/core arXiv query.

    categories: OR inside the category group
    keywords:   OR inside the keyword group
    logic:      AND/OR between category group and keyword group
    """
    cat_q = _category_group(categories)
    key_q = _keywords_group(keywords)

    if cat_q and key_q:
        op = "AND" if (logic or "AND").upper() == "AND" else "OR"
        positive_q = f"({cat_q} {op} {key_q})"
    elif cat_q:
        positive_q = cat_q
    elif key_q:
        positive_q = key_q
    else:
        positive_q = "all:*"

    return positive_q + _exclude_group(exclude_keywords)


def build_related_search_query(
    categories: List[str],
    direct_keywords: List[str],
    method_keywords: List[str],
    context_keywords: List[str],
    exclude_keywords: Optional[List[str]] = None,
) -> str:
    """
    Build a safer Related Research query.

    Structure:

      categories AND (
          direct_related_keywords
          OR
          (method_keywords AND context_keywords)
      )

    This prevents generic terms such as "LLM", "dynamic graph" or
    "online clustering" from flooding the digest with unrelated papers.
    """
    cat_q = _category_group(categories)
    direct_q = _keywords_group(direct_keywords)
    method_q = _keywords_group(method_keywords)
    context_q = _keywords_group(context_keywords)

    related_parts = []
    if direct_q:
        related_parts.append(direct_q)
    if method_q and context_q:
        related_parts.append(f"({method_q} AND {context_q})")

    if related_parts:
        related_q = "(" + " OR ".join(related_parts) + ")"
    else:
        related_q = ""

    if cat_q and related_q:
        positive_q = f"({cat_q} AND {related_q})"
    elif related_q:
        positive_q = related_q
    elif cat_q:
        positive_q = cat_q
    else:
        positive_q = "all:*"

    return positive_q + _exclude_group(exclude_keywords)
