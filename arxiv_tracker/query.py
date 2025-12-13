# arxiv_tracker/query.py
import re
from typing import List

FIELDS = ("ti", "abs", "co")  # 标题/摘要/评论（会议常在 comments）

def _quote(term: str) -> str:
    # 有空格或连字符时加引号，避免被拆词
    t = term.strip()
    if re.search(r'[\s-]', t):
        return f'"{t}"'
    return t

def _field_or(fields: List[str], term: str) -> str:
    q = _quote(term)
    return "(" + " OR ".join(f"{f}:{q}" for f in fields) + ")"

def _expand_variants(kw: str) -> List[str]:
    """为一个关键词生成若干变体：连字符/空格、大小写不敏感"""
    k = kw.strip()
    out = {k}
    if " " in k:
        out.add(k.replace(" ", "-"))
    if "-" in k:
        out.add(k.replace("-", " "))
    return sorted(out, key=len, reverse=True)  # 优先长短语

def _kw_group(kw: str) -> str:
    """
    为一个逻辑关键词构造一个子查询：
    - 先尝试短语精确（含连字符/空格变体）
    - 若包含 'open vocabulary' 与 'segmentation'，再加一个“拆词 AND”备选
    """
    variants = _expand_variants(kw)
    parts = []

    # 1) 短语匹配（多个变体，ti/abs/co）
    for v in variants:
        parts.append(_field_or(FIELDS, v))

    # 2) 针对 open-vocabulary segmentation 的拆词 AND（覆盖更多写法）
    low = kw.lower()
    if ("open vocabulary" in low or "open-vocabulary" in low) and "segmentation" in low:
        ov_terms = ["open vocabulary", "open-vocabulary", "open-vocabulary segmentation", "open vocabulary segmentation"]
        seg_terms = ["segmentation", "image segmentation"]
        ov_or = "(" + " OR ".join(_field_or(FIELDS, t) for t in ov_terms) + ")"
        seg_or = "(" + " OR ".join(_field_or(FIELDS, t) for t in seg_terms) + ")"
        parts.append(f"({ov_or} AND {seg_or})")

    return "(" + " OR ".join(parts) + ")"

def build_search_query(categories: List[str], keywords: List[str], exclude_keywords: List[str] = None, logic: str = "AND") -> str:    
    """
    生成 arXiv API 的 search_query 字符串。
    - categories: ["cs.CV","cs.LG"] -> (cat:cs.CV OR cat:cs.LG)
    - keywords:   每个 kw 变成一个 _kw_group，关键词之间用 OR 连接
    - 组间逻辑：cat_group (AND/OR) kw_group
    - 结构: (正面查询) AND NOT (负面查询)
    """
    cats = [c.strip() for c in (categories or []) if c and c.strip()]
    keys = [k.strip() for k in (keywords or []) if k and k.strip()]
    excs = [e.strip() for e in (exclude_keywords or []) if e and e.strip()] 
    
    cat_q = ""
    key_q = ""
    exc_q = "" 

    if cats:
        cat_q = "(" + " OR ".join(f"cat:{c}" for c in cats) + ")"
    if keys:
        key_q = "(" + " OR ".join(_kw_group(k) for k in keys) + ")"
        
    if excs:
        # 复用 _kw_group 逻辑，也可以只做简单匹配。这里复用逻辑以支持变体。
        # 意思为: NOT ( ("LLM"在标题/摘要) OR ("Large Language Model"在标题/摘要) )
        exc_q = " AND NOT (" + " OR ".join(_kw_group(e) for e in excs) + ")"
        
    # 构建正面查询部分
    positive_q = ""
    if cat_q and key_q:
        op = "AND" if (logic or "AND").upper() == "AND" else "OR"
        positive_q = f"({cat_q} {op} {key_q})"
    elif cat_q:
        positive_q = cat_q
    elif key_q:
        positive_q = key_q
    else:
        positive_q = "all:*"

    # 最终拼接
    return positive_q + exc_q
