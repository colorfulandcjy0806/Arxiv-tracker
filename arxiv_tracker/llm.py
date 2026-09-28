# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import requests


# ==========================================================
# Generic helpers
# ==========================================================

def _json_loose(s: str) -> Dict[str, Any]:
    """Best-effort extraction of the first JSON object from model output."""
    m = re.search(r"\{[\s\S]*\}", s or "")
    if not m:
        return {}

    raw = m.group(0)

    try:
        return json.loads(raw)
    except Exception:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)

        try:
            return json.loads(cleaned)
        except Exception:
            return {}


def _loose_json_load(s: str) -> Dict[str, Any]:
    """Backward-compatible alias."""
    return _json_loose(s)


def _normalize_chat_endpoint(base_url: str) -> str:
    """
    Accept:

    https://api.xxx.com
    https://api.xxx.com/v1
    https://api.xxx.com/v1/chat/completions

    and normalize to Chat Completions endpoint.
    """
    if not base_url:
        raise ValueError("llm.base_url is empty")

    base = base_url.rstrip("/")

    if base.endswith("/chat/completions"):
        return base

    if base.endswith("/v1"):
        return base + "/chat/completions"

    return base + "/v1/chat/completions"


def _chat_completions_request(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 30,
) -> str:
    """OpenAI-compatible Chat Completions request."""

    url = _normalize_chat_endpoint(base_url)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    resp = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=timeout,
    )

    resp.raise_for_status()

    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return data.get("choices", [{}])[0].get("text", "")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        text = value.strip().lower()

        if text in {"true", "1", "yes", "y"}:
            return True

        if text in {"false", "0", "no", "n"}:
            return False

    return default


def _clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except Exception:
        score = default

    return max(0.0, min(1.0, score))


# ==========================================================
# Semantic relevance filter
# ==========================================================

def call_llm_relevance_filter(
    item: Dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    source_track: str = "core",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """
    Classify a paper into core / related / noise before it reaches the email.

    Returns:

    {
        "keep": bool,
        "label": "core" | "related" | "noise",
        "score": float,
        "reason": str
    }
    """

    payload = {
        "source_track": source_track,
        "title": item.get("title") or "",
        "abstract": item.get("summary") or "",
        "primary_category": item.get("primary_category") or "",
        "categories": item.get("categories") or [],
        "comments": item.get("comments") or "",
    }

    sys_prompt = system_prompt.strip() or (
        "You are a strict academic relevance classifier "
        "for Social Event Detection. Return only JSON."
    )

    user_prompt = (
        "Judge whether this paper belongs in a "
        "Social Event Detection literature digest.\n\n"

        "Target task: detect/discover/cluster/track/evolve/extract "
        "real-world events from social-media, social-network, "
        "microblog, or user-generated streams.\n\n"

        "Use exactly one label:\n"

        "- core: the main task is directly Social Event Detection "
        "/ Social Media Event Detection.\n"

        "- related: not directly SED, but clearly transferable to SED "
        "AND still about social-media/social-network streams plus "
        "events/topics.\n"

        "- noise: another meaning of event or only weakly related.\n\n"

        "Typical noise: event cameras, event-based vision, "
        "image/video activity recognition, sound/acoustic events, "
        "medical/clinical events, finance events, cybersecurity events, "
        "generic sensor events, or generic event extraction without "
        "social-media/event-stream context.\n\n"

        "Return STRICT JSON only, using this schema:\n"

        '{"keep": true, "label": "core", "score": 0.93, '
        '"reason": "one short factual sentence"}\n\n'

        f"PAPER:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    text = _chat_completions_request(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=[
            {
                "role": "system",
                "content": sys_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.0,
        max_tokens=220,
        timeout=30,
    )

    data = _json_loose(text)

    label = str(
        data.get("label") or "noise"
    ).strip().lower()

    if label not in {
        "core",
        "related",
        "noise",
    }:
        label = "noise"

    score = _clamp_score(
        data.get("score"),
        0.0,
    )

    keep = _as_bool(
        data.get("keep"),
        label != "noise",
    )

    if label == "noise":
        keep = False

    reason = str(
        data.get("reason") or ""
    ).strip()

    if not reason:
        reason = "No reason returned by relevance classifier."

    return {
        "keep": keep,
        "label": label,
        "score": score,
        "reason": reason,
    }


# ==========================================================
# Bilingual summary
# ==========================================================

def call_llm_bilingual_summary(
    item: Dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt_zh: str = "",
    system_prompt_en: str = "",
) -> Dict[str, str]:

    title = item.get("title") or ""
    summary = item.get("summary") or ""
    comments = item.get("comments") or ""

    venue = (
        item.get("venue_inferred")
        or item.get("journal_ref")
        or ""
    )

    sys_prompt = system_prompt_en or (
        "You are a precise academic assistant. "
        "Summarize papers concisely."
    )

    user_payload = {
        "title": title,
        "abstract": summary,
        "venue_or_comments": venue or comments or "",
    }

    messages = [
        {
            "role": "system",
            "content": sys_prompt,
        },
        {
            "role": "user",
            "content": (
                "Given the paper metadata below, write TWO "
                "concise one-paragraph digests:\n"
                "1) English paragraph first.\n"
                "2) Then a Simplified Chinese paragraph.\n"
                "- Each paragraph must briefly cover motivation, "
                "method, and main experimental results.\n"
                "- Do not include links, bullet lists, markdown, "
                "or headings.\n"
                '- Return STRICT JSON: '
                '{"digest_en": "...", "digest_zh": "..."}\n\n'
                f"DATA:\n"
                f"{json.dumps(user_payload, ensure_ascii=False)}"
            ),
        },
    ]

    text = _chat_completions_request(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=600,
    )

    data = _json_loose(text)

    return {
        "digest_en": (
            data.get("digest_en") or ""
        ).strip(),
        "digest_zh": (
            data.get("digest_zh") or ""
        ).strip(),
    }


# ==========================================================
# Two-stage summary
# ==========================================================

def build_llm_prompt(
    item: Dict[str, Any],
    lang: str = "zh",
    scope: str = "both",
):
    title = item.get("title") or ""

    authors = ", ".join(
        item.get("authors") or []
    )

    venue = (
        item.get("venue_inferred")
        or item.get("journal_ref")
        or ""
    )

    comments = item.get("comments") or ""
    summary = item.get("summary") or ""

    links = {
        "html": item.get("html_url"),
        "pdf": item.get("pdf_url"),
        "code": item.get("code_urls") or [],
        "project": item.get("project_urls") or [],
        "other": item.get("other_urls") or [],
    }

    meta = {
        "title": title,
        "authors": authors,
        "venue": venue,
        "comments": comments,
        "summary": summary,
        "links": links,
    }

    ask_lang = (
        "中文"
        if lang == "zh"
        else "English"
    )

    user_prompt = f"""
请阅读以下论文元信息(JSON)，用{ask_lang}输出“两阶段摘要”：

1) TL;DR（1~2 句，先总后分，避免口号）

2) **Method Card**
任务/动机、核心方法、关键设计、数据与指标、
主要结果与结论、局限与未来工作、保留链接
（PDF/代码/项目页）

3) **Discussion Questions**
3~5 个高质量问题（可用于组会讨论）

请保留所有给定链接，不要臆造。
scope="{scope}" 表示输出范围（tldr/full/both）。

JSON:
{json.dumps(meta, ensure_ascii=False, indent=2)}
""".strip()

    return user_prompt


def call_llm_two_stage(
    item: Dict[str, Any],
    lang: str,
    scope: str,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str = "",
) -> Dict[str, str]:

    messages = []

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    messages.append(
        {
            "role": "user",
            "content": build_llm_prompt(
                item,
                lang=lang,
                scope=scope,
            ),
        }
    )

    text = _chat_completions_request(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=900,
    ).strip()

    tldr = ""
    full_md = ""

    if (
        "TL;DR" in text
        or "TLDR" in text
        or "Tl;dr" in text
    ):

        parts = text.splitlines()

        tldr_lines = []
        rest_lines = []
        in_tldr = False

        for ln in parts:
            if (
                "TL;DR" in ln
                or "TLDR" in ln
                or "Tl;dr" in ln
            ):
                in_tldr = True

                t = (
                    ln.replace("TL;DR", "")
                    .replace("TLDR", "")
                    .replace("Tl;dr", "")
                )

                tldr_lines.append(
                    t.strip(" :：")
                )

            elif in_tldr and (
                ln.strip().startswith("**Method")
                or ln.strip()
                .lower()
                .startswith("**discussion")
            ):
                in_tldr = False
                rest_lines.append(ln)

            elif in_tldr:
                tldr_lines.append(ln)

            else:
                rest_lines.append(ln)

        tldr = " ".join(
            [
                s.strip()
                for s in tldr_lines
                if s.strip()
            ]
        )

        full_md = "\n".join(
            rest_lines
        ).strip()

    else:
        full_md = text

    return {
        "tldr": tldr,
        "full_md": full_md,
    }


# ==========================================================
# Translation
# ==========================================================

def call_llm_translate(
    item: Dict[str, Any],
    target_lang: str,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str = "",
) -> Dict[str, str]:

    title = item.get("title") or ""
    summary = item.get("summary") or ""
    comments = item.get("comments") or ""

    want_comments = bool(
        comments.strip()
    )

    schema_keys = [
        "title_zh",
        "summary_zh",
    ] + (
        ["comments_zh"]
        if want_comments
        else []
    )

    sys_prompt = system_prompt or (
        "You are a precise academic translator. "
        "Translate to Simplified Chinese concisely "
        "and faithfully; keep technical terms."
    )

    inst = f"""
Translate the following fields into Simplified Chinese.

Return ONLY compact JSON with keys {schema_keys}
(omit keys you can't translate).

Do not add commentary.

DATA:
{json.dumps({
    "title": title,
    "summary": summary,
    "comments": comments,
}, ensure_ascii=False, indent=2)}
""".strip()

    messages = [
        {
            "role": "system",
            "content": sys_prompt,
        },
        {
            "role": "user",
            "content": inst,
        },
    ]

    text = _chat_completions_request(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=600,
    ).strip()

    data = _loose_json_load(text)

    out: Dict[str, str] = {}

    if isinstance(data, dict):

        if (
            "title_zh" in data
            and isinstance(
                data["title_zh"],
                str,
            )
        ):
            out["title_zh"] = (
                data["title_zh"].strip()
            )

        if (
            "summary_zh" in data
            and isinstance(
                data["summary_zh"],
                str,
            )
        ):
            out["summary_zh"] = (
                data["summary_zh"].strip()
            )

        if (
            "comments_zh" in data
            and isinstance(
                data["comments_zh"],
                str,
            )
        ):
            out["comments_zh"] = (
                data["comments_zh"].strip()
            )

    return out
