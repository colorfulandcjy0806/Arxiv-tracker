# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import traceback

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

import click

from .client import fetch_arxiv_feed
from .config import Settings
from .email_template import render_email_html
from .exporter import md_to_pdf
from .llm import (
    call_llm_relevance_filter,
    call_llm_translate,
)
from .output import save_json, save_markdown
from .parser import parse_feed
from .query import (
    build_related_search_query,
    build_search_query,
)
from .summarizer import build_two_stage_summary


_SENT_EMAIL = False


def _split_categories(
    values: Iterable[str],
) -> List[str]:

    out: List[str] = []

    for value in values or []:

        if not value:
            continue

        parts = re.split(
            r"\s*,\s*|\s*;\s*|/",
            value.strip(),
        )

        out.extend(
            [
                part
                for part in parts
                if part
            ]
        )

    return out


def _split_keywords(
    values: Iterable[str],
) -> List[str]:

    out: List[str] = []

    for value in values or []:

        if not value:
            continue

        parts = re.split(
            r"\s*,\s*|\s*;\s*",
            value.strip(),
        )

        out.extend(
            [
                part
                for part in parts
                if part
            ]
        )

    return out


def _load_raw_cfg(
    maybe_path: Optional[str],
) -> Dict[str, Any]:

    import yaml

    path = (
        maybe_path
        or "config.yaml"
    )

    if not os.path.exists(path):
        return {}

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        return yaml.safe_load(f) or {}


def _extract_stamp_from_path(
    path: str,
) -> str:

    try:

        name = os.path.basename(
            path or ""
        )

        match = re.search(
            r"arxiv_(\d{8}_\d{6})",
            name,
        )

        if match:
            return match.group(1)

    except Exception:
        pass

    return time.strftime(
        "%Y%m%d"
    )


def _norm_addr(
    value: str,
) -> str:

    return re.sub(
        r"\s+",
        "",
        value or "",
    ).lower()


def _dedup_addrs(
    seq: Iterable[str],
) -> List[str]:

    seen: Set[str] = set()
    out: List[str] = []

    for value in seq or []:

        key = _norm_addr(
            value
        )

        if (
            key
            and key not in seen
        ):

            out.append(
                value.strip()
            )

            seen.add(key)

    return out


def _parse_dt(
    value: str,
) -> Optional[datetime]:

    if not value:
        return None

    text = value.replace(
        "Z",
        "+00:00",
    )

    try:
        return datetime.fromisoformat(
            text
        ).astimezone(
            timezone.utc
        )

    except Exception:
        return None


def _normalize_arxiv_id(
    value: str,
) -> str:

    if not value:
        return ""

    text = str(
        value
    ).strip().rstrip("/")

    match = re.search(
        r"arxiv\.org/(?:abs|pdf)/([^?#]+)",
        text,
        flags=re.I,
    )

    if match:
        text = match.group(1)

    text = re.sub(
        r"\.pdf$",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"v\d+$",
        "",
        text,
        flags=re.I,
    )

    return text.strip().lower()


def _item_dedup_key(
    item: Dict[str, Any],
) -> str:

    key = _normalize_arxiv_id(
        item.get("id")
        or item.get("html_url")
        or item.get("pdf_url")
        or ""
    )

    if key:
        return key

    title = re.sub(
        r"\s+",
        " ",
        (
            item.get("title")
            or ""
        ).strip().lower(),
    )

    if title:
        return f"title:{title}"

    return ""


def _load_seen_ids(
    state_path: str,
) -> Set[str]:

    if (
        not state_path
        or not os.path.exists(
            state_path
        )
    ):
        return set()

    try:

        with open(
            state_path,
            "r",
            encoding="utf-8",
        ) as f:

            data = (
                json.load(f)
                or {}
            )

        if (
            isinstance(data, dict)
            and "ids" in data
        ):
            raw_ids = (
                data.get("ids")
                or []
            )

        elif isinstance(
            data,
            dict,
        ):
            raw_ids = list(
                data.keys()
            )

        elif isinstance(
            data,
            list,
        ):
            raw_ids = data

        else:
            raw_ids = []

        return {
            norm
            for raw in raw_ids
            if (
                norm :=
                _normalize_arxiv_id(
                    str(raw)
                )
            )
        }

    except Exception:
        return set()


def _item_time_for_sort(
    item: Dict[str, Any],
    sort_by: str,
) -> Optional[datetime]:

    if sort_by == "submittedDate":

        return (
            _parse_dt(
                item.get("published")
            )
            or
            _parse_dt(
                item.get("updated")
            )
        )

    return (
        _parse_dt(
            item.get("updated")
        )
        or
        _parse_dt(
            item.get("published")
        )
    )


def _fetch_track(
    *,
    query: str,
    track: str,
    limit: int,
    sort_by: str,
    sort_order: str,
    cutoff: Optional[datetime],
    unique_only: bool,
    seen_ids: Set[str],
    current_ids: Set[str],
    verbose: bool,
) -> List[Dict[str, Any]]:

    limit = max(
        0,
        int(limit or 0),
    )

    if (
        limit <= 0
        or not query
    ):
        return []

    page_size = min(
        200,
        max(
            25,
            limit * 5,
        ),
    )

    max_pages = 20
    start = 0

    collected: List[
        Dict[str, Any]
    ] = []

    reached_cutoff = False

    for page_index in range(
        max_pages
    ):

        xml = fetch_arxiv_feed(
            query,
            start=start,
            max_results=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        page_items = (
            parse_feed(xml)
            or []
        )

        if verbose:

            click.echo(
                f"[{track}] "
                f"page={page_index + 1} "
                f"start={start} "
                f"fetched={len(page_items)} "
                f"collected={len(collected)}"
            )

        if not page_items:
            break

        for item in page_items:

            item_time = (
                _item_time_for_sort(
                    item,
                    sort_by,
                )
            )

            if (
                cutoff
                and item_time
                and item_time < cutoff
            ):

                reached_cutoff = True
                break

            dedup_key = (
                _item_dedup_key(
                    item
                )
            )

            if (
                unique_only
                and dedup_key
                and dedup_key in seen_ids
            ):
                continue

            if (
                dedup_key
                and dedup_key in current_ids
            ):
                continue

            item["_track"] = track

            collected.append(
                item
            )

            if dedup_key:
                current_ids.add(
                    dedup_key
                )

            if len(
                collected
            ) >= limit:
                break

        if (
            len(collected) >= limit
            or reached_cutoff
        ):
            break

        if (
            len(page_items)
            < page_size
        ):
            break

        start += page_size

    return collected


def _fallback_fetch(
    *,
    query: str,
    track: str,
    limit: int,
    sort_by: str,
    sort_order: str,
    current_ids: Set[str],
) -> List[Dict[str, Any]]:

    if (
        limit <= 0
        or not query
    ):
        return []

    xml = fetch_arxiv_feed(
        query,
        start=0,
        max_results=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    page_items = (
        parse_feed(xml)
        or []
    )

    out: List[
        Dict[str, Any]
    ] = []

    for item in page_items:

        key = _item_dedup_key(
            item
        )

        if (
            key
            and key in current_ids
        ):
            continue

        item["_track"] = track

        out.append(item)

        if key:
            current_ids.add(
                key
            )

        if len(out) >= limit:
            break

    return out


def _hard_noise_match(
    item: Dict[str, Any],
    keywords: List[str],
) -> str:

    if not keywords:
        return ""

    text = " ".join(
        [
            item.get("title")
            or "",
            item.get("summary")
            or "",
            item.get("comments")
            or "",
        ]
    ).lower()

    for keyword in keywords:

        key = (
            keyword
            or ""
        ).strip().lower()

        if (
            key
            and key in text
        ):
            return keyword

    return ""


def _sort_newest_first(
    items: List[Dict[str, Any]],
    sort_by: str,
) -> List[Dict[str, Any]]:

    def _key(
        item: Dict[str, Any],
    ) -> float:

        dt = _item_time_for_sort(
            item,
            sort_by,
        )

        if dt:
            return dt.timestamp()

        return 0.0

    return sorted(
        items,
        key=_key,
        reverse=True,
    )


def _trim_by_track(
    items: List[Dict[str, Any]],
    *,
    max_results: int,
    core_max_results: int,
    related_max_results: int,
    sort_by: str,
) -> List[Dict[str, Any]]:

    core = _sort_newest_first(
        [
            x
            for x in items
            if (
                x.get("_track")
                == "core"
            )
        ],
        sort_by,
    )[
        :core_max_results
    ]

    related = _sort_newest_first(
        [
            x
            for x in items
            if (
                x.get("_track")
                == "related"
            )
        ],
        sort_by,
    )[
        :related_max_results
    ]

    out = (
        core
        + related
    )

    if max_results > 0:

        out = out[
            :max_results
        ]

    return out


def _apply_relevance_filter(
    candidates: List[Dict[str, Any]],
    *,
    relevance_cfg: Dict[str, Any],
    llm_cfg: Dict[str, Any],
    max_results: int,
    core_max_results: int,
    related_max_results: int,
    sort_by: str,
    verbose: bool,
) -> List[Dict[str, Any]]:

    enabled = bool(
        relevance_cfg.get(
            "enabled",
            False,
        )
    )

    if not enabled:

        return _trim_by_track(
            candidates,
            max_results=max_results,
            core_max_results=core_max_results,
            related_max_results=related_max_results,
            sort_by=sort_by,
        )

    core_threshold = float(
        relevance_cfg.get(
            "core_threshold",
            0.78,
        )
    )

    related_threshold = float(
        relevance_cfg.get(
            "related_threshold",
            0.70,
        )
    )

    fail_open = bool(
        relevance_cfg.get(
            "fail_open",
            True,
        )
    )

    hard_noise_keywords = (
        relevance_cfg.get(
            "hard_noise_keywords"
        )
        or []
    )

    system_prompt = (
        relevance_cfg.get(
            "system_prompt"
        )
        or ""
    )

    api_key = (
        llm_cfg.get("api_key")
        or
        os.getenv(
            llm_cfg.get(
                "api_key_env"
            )
            or
            "OPENAI_API_KEY",
            "",
        )
    )

    if not api_key:

        click.secho(
            "[Relevance] "
            "LLM API Key missing. "
            +
            (
                "Fail-open: keep query candidates."
                if fail_open
                else
                "Fail-closed: drop all candidates."
            ),
            fg="yellow",
        )

        if not fail_open:
            return []

        return _trim_by_track(
            candidates,
            max_results=max_results,
            core_max_results=core_max_results,
            related_max_results=related_max_results,
            sort_by=sort_by,
        )

    accepted: List[
        Dict[str, Any]
    ] = []

    dropped = 0

    for idx, item in enumerate(
        candidates,
        1,
    ):

        title = (
            item.get("title")
            or ""
        )

        source_track = (
            item.get("_track")
            or "core"
        )

        hard_match = (
            _hard_noise_match(
                item,
                hard_noise_keywords,
            )
        )

        if hard_match:

            item["_relevance_label"] = (
                "noise"
            )

            item["_relevance_score"] = (
                0.0
            )

            item[
                "_relevance_reason"
            ] = (
                "hard-noise keyword "
                f"matched: {hard_match}"
            )

            dropped += 1

            if verbose:

                click.echo(
                    "[Relevance] "
                    f"DROP hard-noise "
                    f"{idx}/{len(candidates)} "
                    f"[{source_track}] "
                    f"{title[:90]} "
                    f"({hard_match})"
                )

            continue

        try:

            result = (
                call_llm_relevance_filter(
                    item,
                    base_url=llm_cfg.get(
                        "base_url",
                        "",
                    ),
                    model=llm_cfg.get(
                        "model",
                        "",
                    ),
                    api_key=api_key,
                    source_track=source_track,
                    system_prompt=system_prompt,
                )
            )

            label = (
                result.get("label")
                or "noise"
            )

            score = float(
                result.get("score")
                or 0.0
            )

            keep = bool(
                result.get("keep")
            )

            reason = (
                result.get("reason")
                or ""
            )

            item[
                "_relevance_label"
            ] = label

            item[
                "_relevance_score"
            ] = score

            item[
                "_relevance_reason"
            ] = reason

            item[
                "_source_track"
            ] = source_track

            accepted_now = False

            if (
                keep
                and label == "core"
                and score >= core_threshold
            ):

                item["_track"] = "core"
                accepted_now = True

            elif (
                keep
                and label == "related"
                and score >= related_threshold
            ):

                item["_track"] = "related"
                accepted_now = True

            if accepted_now:

                accepted.append(
                    item
                )

                if verbose:

                    click.echo(
                        "[Relevance] "
                        f"KEEP "
                        f"{idx}/{len(candidates)} "
                        f"label={label} "
                        f"score={score:.2f} "
                        f"[{source_track}"
                        f"->{item['_track']}] "
                        f"{title[:90]}"
                    )

            else:

                dropped += 1

                if verbose:

                    click.echo(
                        "[Relevance] "
                        f"DROP "
                        f"{idx}/{len(candidates)} "
                        f"label={label} "
                        f"score={score:.2f} "
                        f"[{source_track}] "
                        f"{title[:90]}"
                    )

                    if reason:

                        click.echo(
                            "            "
                            f"reason: {reason}"
                        )

        except Exception as exc:

            if fail_open:

                item[
                    "_relevance_label"
                ] = source_track

                item[
                    "_relevance_score"
                ] = 0.0

                item[
                    "_relevance_reason"
                ] = (
                    "classifier failed; "
                    f"fail-open: {exc}"
                )

                accepted.append(
                    item
                )

                click.secho(
                    "[Relevance] "
                    "classifier failed, "
                    "fail-open for "
                    f"{title[:80]}: "
                    f"{exc}",
                    fg="yellow",
                )

            else:

                dropped += 1

                click.secho(
                    "[Relevance] "
                    "classifier failed, "
                    "drop "
                    f"{title[:80]}: "
                    f"{exc}",
                    fg="yellow",
                )

    selected = _trim_by_track(
        accepted,
        max_results=max_results,
        core_max_results=core_max_results,
        related_max_results=related_max_results,
        sort_by=sort_by,
    )

    click.echo(
        "[Relevance] "
        f"candidates={len(candidates)} "
        f"accepted_before_quota="
        f"{len(accepted)} "
        f"selected={len(selected)} "
        f"dropped={dropped}"
    )

    return selected


@click.group()
def cli():
    """arxiv-tracker CLI."""
    pass


@cli.command("run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(
        exists=True
    ),
    help="配置文件路径（YAML）",
)
@click.option(
    "--categories",
    multiple=True,
    help="Core 学科分类",
)
@click.option(
    "--related-categories",
    multiple=True,
    help="Related 学科分类",
)
@click.option(
    "--keywords",
    multiple=True,
    help="核心 SED 关键词",
)
@click.option(
    "--related-keywords",
    multiple=True,
)
@click.option(
    "--related-method-keywords",
    multiple=True,
)
@click.option(
    "--related-social-context-keywords",
    multiple=True,
)
@click.option(
    "--related-event-context-keywords",
    multiple=True,
)
@click.option(
    "--related-context-keywords",
    multiple=True,
    help="兼容旧版配置",
)
@click.option(
    "--exclude-keywords",
    multiple=True,
)
@click.option(
    "--logic",
    type=click.Choice(
        [
            "AND",
            "OR",
        ],
        case_sensitive=False,
    ),
    default=None,
)
@click.option(
    "--max-results",
    type=int,
    default=None,
)
@click.option(
    "--core-max-results",
    type=int,
    default=None,
)
@click.option(
    "--related-max-results",
    type=int,
    default=None,
)
@click.option(
    "--sort-by",
    type=click.Choice(
        [
            "submittedDate",
            "lastUpdatedDate",
        ]
    ),
    default=None,
)
@click.option(
    "--sort-order",
    type=click.Choice(
        [
            "ascending",
            "descending",
        ]
    ),
    default=None,
)
@click.option(
    "--lang",
    type=click.Choice(
        [
            "zh",
            "en",
            "both",
        ]
    ),
    default=None,
)
@click.option(
    "--summary-mode",
    type=click.Choice(
        [
            "none",
            "heuristic",
            "llm",
        ]
    ),
    default=None,
)
@click.option(
    "--summary-scope",
    type=click.Choice(
        [
            "tldr",
            "full",
            "both",
        ]
    ),
    default=None,
)
@click.option(
    "--email",
    "email_enabled",
    is_flag=True,
    default=None,
)
@click.option(
    "--email-detail",
    type=click.Choice(
        [
            "simple",
            "full",
        ]
    ),
    default=None,
)
@click.option(
    "--email-max-items",
    type=int,
    default=None,
)
@click.option(
    "--out-dir",
    default="outputs",
)
@click.option(
    "--verbose",
    is_flag=True,
)
@click.option(
    "--translate",
    "translate_enabled",
    is_flag=True,
    default=None,
)
@click.option(
    "--translate-lang",
    type=click.Choice(
        ["zh"]
    ),
    default=None,
)
@click.option(
    "--pdf",
    "pdf_enabled",
    is_flag=True,
    default=False,
)
@click.option(
    "--site-dir",
    default=None,
)
@click.option(
    "--site-url",
    default=None,
)
@click.option(
    "--no-email",
    is_flag=True,
)
def run(
    config_path,
    categories,
    related_categories,
    keywords,
    related_keywords,
    related_method_keywords,
    related_social_context_keywords,
    related_event_context_keywords,
    related_context_keywords,
    exclude_keywords,
    logic,
    max_results,
    core_max_results,
    related_max_results,
    sort_by,
    sort_order,
    lang,
    summary_mode,
    summary_scope,
    email_enabled,
    email_detail,
    email_max_items,
    out_dir,
    verbose,
    translate_enabled,
    translate_lang,
    pdf_enabled,
    site_dir,
    site_url,
    no_email: bool,
):

    try:

        if verbose:
            click.echo(
                "[Run] Start"
            )

        cfg = (
            Settings.from_file(
                config_path
            )
            if config_path
            else Settings()
        )

        cats = _split_categories(
            categories
        )

        related_cats = (
            _split_categories(
                related_categories
            )
        )

        core_keys = _split_keywords(
            keywords
        )

        related_keys = (
            _split_keywords(
                related_keywords
            )
        )

        related_method_keys = (
            _split_keywords(
                related_method_keywords
            )
        )

        related_social_keys = (
            _split_keywords(
                related_social_context_keywords
            )
        )

        related_event_keys = (
            _split_keywords(
                related_event_context_keywords
            )
        )

        legacy_related_context_keys = (
            _split_keywords(
                related_context_keywords
            )
        )

        ex_keys = _split_keywords(
            exclude_keywords
        )

        cfg.merge_cli(
            categories=(
                cats
                or None
            ),
            related_categories=(
                related_cats
                or None
            ),
            keywords=(
                core_keys
                or None
            ),
            related_keywords=(
                related_keys
                or None
            ),
            related_method_keywords=(
                related_method_keys
                or None
            ),
            related_social_context_keywords=(
                related_social_keys
                or None
            ),
            related_event_context_keywords=(
                related_event_keys
                or None
            ),
            related_context_keywords=(
                legacy_related_context_keys
                or None
            ),
            exclude_keywords=(
                ex_keys
                or None
            ),
            logic=(
                logic
                or cfg.logic
            ),
            max_results=(
                max_results
                if max_results
                is not None
                else cfg.max_results
            ),
            core_max_results=(
                core_max_results
                if core_max_results
                is not None
                else cfg.core_max_results
            ),
            related_max_results=(
                related_max_results
                if related_max_results
                is not None
                else cfg.related_max_results
            ),
            sort_by=(
                sort_by
                or cfg.sort_by
            ),
            sort_order=(
                sort_order
                or cfg.sort_order
            ),
        )

        raw_cfg = _load_raw_cfg(
            config_path
        )

        lang = (
            lang
            or raw_cfg.get(
                "lang",
                "both",
            )
        )

        cfg.max_results = max(
            0,
            int(
                cfg.max_results
                or 0
            ),
        )

        cfg.core_max_results = max(
            0,
            int(
                cfg.core_max_results
                or 0
            ),
        )

        cfg.related_max_results = max(
            0,
            int(
                cfg.related_max_results
                or 0
            ),
        )

        if cfg.max_results:

            cfg.core_max_results = min(
                cfg.core_max_results,
                cfg.max_results,
            )

            cfg.related_max_results = min(
                cfg.related_max_results,
                max(
                    0,
                    cfg.max_results
                    -
                    cfg.core_max_results,
                ),
            )

        summary_cfg = (
            raw_cfg.get(
                "summary",
                {},
            )
            or {}
        )

        llm_cfg = (
            raw_cfg.get(
                "llm",
                {},
            )
            or {}
        )

        mode = (
            summary_mode
            or summary_cfg.get(
                "mode",
                "none",
            )
        )

        scope = (
            summary_scope
            or summary_cfg.get(
                "scope",
                "both",
            )
        )

        relevance_cfg = (
            raw_cfg.get(
                "relevance_filter",
                {},
            )
            or {}
        )

        relevance_enabled = bool(
            relevance_cfg.get(
                "enabled",
                False,
            )
        )

        candidate_multiplier = max(
            1,
            int(
                relevance_cfg.get(
                    "candidate_multiplier",
                    1,
                )
                or 1
            ),
        )

        trans_cfg = (
            raw_cfg.get(
                "translate",
                {},
            )
            or {}
        ).copy()

        if (
            translate_enabled
            is not None
        ):
            trans_cfg[
                "enabled"
            ] = translate_enabled

        if translate_lang:
            trans_cfg[
                "lang"
            ] = translate_lang

        trans_cfg.setdefault(
            "fields",
            [
                "title",
                "summary",
            ],
        )

        email_cfg = (
            raw_cfg.get(
                "email",
                {},
            )
            or {}
        ).copy()

        if (
            email_enabled
            is not None
        ):
            email_cfg[
                "enabled"
            ] = bool(
                email_enabled
            )

        if email_detail:
            email_cfg[
                "detail"
            ] = email_detail

        if (
            email_max_items
            is not None
        ):
            email_cfg[
                "max_items"
            ] = int(
                email_max_items
            )

        if no_email:
            email_cfg[
                "enabled"
            ] = False

        email_cfg.setdefault(
            "enabled",
            False,
        )

        email_cfg.setdefault(
            "detail",
            "full",
        )

        email_cfg.setdefault(
            "max_items",
            50,
        )

        fresh_cfg = (
            raw_cfg.get(
                "freshness"
            )
            or {}
        )

        since_days = int(
            fresh_cfg.get(
                "since_days",
                0,
            )
            or 0
        )

        unique_only = bool(
            fresh_cfg.get(
                "unique_only",
                False,
            )
        )

        state_path = (
            fresh_cfg.get(
                "state_path",
                ".state/seen.json",
            )
        )

        fallback_when_empty = bool(
            fresh_cfg.get(
                "fallback_when_empty",
                False,
            )
        )

        mark_seen_on_site = bool(
            fresh_cfg.get(
                "mark_seen_on_site",
                False,
            )
        )

        seen_ids = (
            _load_seen_ids(
                state_path
            )
            if unique_only
            else set()
        )

        cutoff = (
            datetime.now(
                timezone.utc
            )
            -
            timedelta(
                days=since_days
            )
            if since_days > 0
            else None
        )

        if verbose:

            click.echo(
                "[Run] core categories        : "
                f"{cfg.categories}"
            )

            click.echo(
                "[Run] related categories     : "
                f"{cfg.related_categories}"
            )

            click.echo(
                "[Run] core keywords          : "
                f"{cfg.keywords}"
            )

            click.echo(
                "[Run] related keywords       : "
                f"{cfg.related_keywords}"
            )

            click.echo(
                "[Run] related method keywords: "
                f"{cfg.related_method_keywords}"
            )

            click.echo(
                "[Run] related social context : "
                f"{cfg.related_social_context_keywords}"
            )

            click.echo(
                "[Run] related event context  : "
                f"{cfg.related_event_context_keywords}"
            )

            click.echo(
                "[Run] final limits           : "
                f"total={cfg.max_results}, "
                f"core={cfg.core_max_results}, "
                f"related={cfg.related_max_results}"
            )

            click.echo(
                "[Relevance] "
                f"enabled={relevance_enabled}, "
                f"candidate_multiplier="
                f"{candidate_multiplier}"
            )

            click.echo(
                "[Run] sort                   : "
                f"{cfg.sort_by}/"
                f"{cfg.sort_order}"
            )

            click.echo(
                "[Run] summary                : "
                f"{mode}/{scope}"
            )

            click.echo(
                "[Run] lang                   : "
                f"{lang}"
            )

            click.echo(
                "[Freshness] "
                f"since_days={since_days}, "
                f"unique_only={unique_only}, "
                f"seen={len(seen_ids)}, "
                f"state_path='{state_path}', "
                f"fallback_when_empty="
                f"{fallback_when_empty}, "
                f"mark_seen_on_site="
                f"{mark_seen_on_site}"
            )

        core_q = build_search_query(
            cfg.categories,
            cfg.keywords,
            cfg.exclude_keywords,
            cfg.logic,
        )

        related_q = (
            build_related_search_query(
                (
                    cfg.related_categories
                    or cfg.categories
                ),
                cfg.related_keywords,
                cfg.related_method_keywords,
                cfg.related_social_context_keywords,
                cfg.related_event_context_keywords,
                cfg.exclude_keywords,
            )
        )

        click.echo(
            f"[Core Query] {core_q}"
        )

        click.echo(
            f"[Related Query] "
            f"{related_q}"
        )

        core_fetch_limit = (
            cfg.core_max_results
            *
            (
                candidate_multiplier
                if relevance_enabled
                else 1
            )
        )

        related_fetch_limit = (
            cfg.related_max_results
            *
            (
                candidate_multiplier
                if relevance_enabled
                else 1
            )
        )

        current_ids: Set[
            str
        ] = set()

        core_candidates = (
            _fetch_track(
                query=core_q,
                track="core",
                limit=core_fetch_limit,
                sort_by=cfg.sort_by,
                sort_order=cfg.sort_order,
                cutoff=cutoff,
                unique_only=unique_only,
                seen_ids=seen_ids,
                current_ids=current_ids,
                verbose=verbose,
            )
        )

        related_candidates = (
            _fetch_track(
                query=related_q,
                track="related",
                limit=related_fetch_limit,
                sort_by=cfg.sort_by,
                sort_order=cfg.sort_order,
                cutoff=cutoff,
                unique_only=unique_only,
                seen_ids=seen_ids,
                current_ids=current_ids,
                verbose=verbose,
            )
        )

        candidates = (
            core_candidates
            +
            related_candidates
        )

        items = (
            _apply_relevance_filter(
                candidates,
                relevance_cfg=(
                    relevance_cfg
                ),
                llm_cfg=llm_cfg,
                max_results=(
                    cfg.max_results
                ),
                core_max_results=(
                    cfg.core_max_results
                ),
                related_max_results=(
                    cfg.related_max_results
                ),
                sort_by=cfg.sort_by,
                verbose=verbose,
            )
        )

        if (
            not items
            and fallback_when_empty
        ):

            current_ids.clear()

            core_fallback = (
                _fallback_fetch(
                    query=core_q,
                    track="core",
                    limit=core_fetch_limit,
                    sort_by=cfg.sort_by,
                    sort_order=cfg.sort_order,
                    current_ids=current_ids,
                )
            )

            related_fallback = (
                _fallback_fetch(
                    query=related_q,
                    track="related",
                    limit=related_fetch_limit,
                    sort_by=cfg.sort_by,
                    sort_order=cfg.sort_order,
                    current_ids=current_ids,
                )
            )

            items = (
                _apply_relevance_filter(
                    (
                        core_fallback
                        +
                        related_fallback
                    ),
                    relevance_cfg=(
                        relevance_cfg
                    ),
                    llm_cfg=llm_cfg,
                    max_results=(
                        cfg.max_results
                    ),
                    core_max_results=(
                        cfg.core_max_results
                    ),
                    related_max_results=(
                        cfg.related_max_results
                    ),
                    sort_by=cfg.sort_by,
                    verbose=verbose,
                )
            )

        if not items:

            click.secho(
                "[Info] No new relevant "
                "items after freshness/"
                "dedup/relevance filtering.",
                fg="yellow",
            )

        else:

            click.echo(
                "[Info] Final items: "
                f"total={len(items)}, "
                f"core={len([x for x in items if x.get('_track') == 'core'])}, "
                f"related={len([x for x in items if x.get('_track') == 'related'])}"
            )

        scrape_cfg = (
            raw_cfg.get(
                "scrape"
            )
            or {}
        )

        scrape_html = bool(
            scrape_cfg.get(
                "html",
                True,
            )
        )

        scrape_pdf_if_missing = bool(
            scrape_cfg.get(
                "pdf_if_missing",
                True,
            )
        )

        scrape_pdf_always = bool(
            scrape_cfg.get(
                "pdf_first_page",
                False,
            )
        )

        scrape_timeout = int(
            scrape_cfg.get(
                "timeout",
                10,
            )
        )

        from .extrascrape import augment_item_links

        if verbose:

            click.echo(
                "[Scrape] "
                f"html={scrape_html} "
                f"pdf_if_missing="
                f"{scrape_pdf_if_missing} "
                f"pdf_first_page="
                f"{scrape_pdf_always} "
                f"timeout={scrape_timeout}"
            )

        for item in items:

            try:

                added = (
                    augment_item_links(
                        item,
                        html=scrape_html,
                        pdf_if_missing=(
                            scrape_pdf_if_missing
                        ),
                        pdf_first_page=(
                            scrape_pdf_always
                        ),
                        timeout=(
                            scrape_timeout
                        ),
                    )
                )

                if (
                    verbose
                    and added > 0
                ):

                    click.echo(
                        "[Scrape] "
                        f"+{added} "
                        "code link(s) for "
                        f"{(item.get('id') or '')[:32]}"
                    )

            except Exception as exc:

                click.secho(
                    "[Scrape] 补链失败 "
                    f"{(item.get('id') or '')[:18]}"
                    f"...: {exc}",
                    fg="yellow",
                )

        summaries_zh: Dict[
            str,
            Dict[str, str],
        ] = {}

        summaries_en: Dict[
            str,
            Dict[str, str],
        ] = {}

        def _sum_for_lang(
            target_lang: str,
        ) -> Dict[
            str,
            Dict[str, str],
        ]:

            out: Dict[
                str,
                Dict[str, str],
            ] = {}

            for item in items:

                sid = (
                    item.get("id")
                    or ""
                )

                out[sid] = (
                    build_two_stage_summary(
                        item=item,
                        mode=mode,
                        lang=target_lang,
                        scope=scope,
                        llm_cfg=llm_cfg,
                    )
                )

            return out

        if lang in (
            "zh",
            "both",
        ):
            summaries_zh = (
                _sum_for_lang(
                    "zh"
                )
            )

        if lang in (
            "en",
            "both",
        ):
            summaries_en = (
                _sum_for_lang(
                    "en"
                )
            )

        translations: Dict[
            str,
            Dict[str, str],
        ] = {}

        if (
            trans_cfg.get(
                "enabled"
            )
            and
            trans_cfg.get(
                "lang",
                "zh",
            )
            == "zh"
        ):

            api_key = (
                llm_cfg.get(
                    "api_key"
                )
                or
                os.getenv(
                    llm_cfg.get(
                        "api_key_env"
                    )
                    or
                    "OPENAI_API_KEY",
                    "",
                )
            )

            if not api_key:

                click.secho(
                    "[Translate] 跳过："
                    "未找到 LLM API Key",
                    fg="yellow",
                )

            else:

                for item in items:

                    sid = (
                        item.get("id")
                        or ""
                    )

                    try:

                        translations[
                            sid
                        ] = (
                            call_llm_translate(
                                item=item,
                                target_lang="zh",
                                base_url=(
                                    llm_cfg.get(
                                        "base_url",
                                        "",
                                    )
                                ),
                                model=(
                                    llm_cfg.get(
                                        "model",
                                        "",
                                    )
                                ),
                                api_key=(
                                    api_key
                                ),
                                system_prompt=(
                                    llm_cfg.get(
                                        "system_prompt_translate_zh",
                                        "",
                                    )
                                ),
                            )
                        )

                    except Exception as exc:

                        click.secho(
                            "[Translate] "
                            f"失败 "
                            f"{sid[:18]}"
                            f"...: {exc}",
                            fg="red",
                        )

        if not items:

            click.echo(
                "（今日暂无新增相关论文，"
                "不发送邮件）"
            )

        for idx, item in enumerate(
            items,
            1,
        ):

            track_label = (
                "SED"
                if item.get(
                    "_track"
                )
                == "core"
                else "RELATED"
            )

            title = (
                item.get(
                    "title",
                    "",
                )
            )

            venue = (
                item.get(
                    "venue_inferred"
                )
                or
                item.get(
                    "journal_ref"
                )
                or ""
            )

            score = item.get(
                "_relevance_score"
            )

            reason = (
                item.get(
                    "_relevance_reason"
                )
                or ""
            )

            click.echo(
                f"{idx:02d}. "
                f"[{track_label}] "
                f"{title}  "
                f"[{' / '.join(item.get('authors', []))}]"
            )

            if venue:

                click.echo(
                    f"    Venue: "
                    f"{venue}"
                )

            click.echo(
                "    Time: "
                f"{item.get('published', '—')} "
                " -> "
                f"{item.get('updated', '—')}"
            )

            if score is not None:

                click.echo(
                    "    Relevance: "
                    f"{float(score):.2f} "
                    f"| {reason}"
                )

            if item.get(
                "pdf_url"
            ):

                click.echo(
                    "    PDF : "
                    f"{item['pdf_url']}"
                )

            sid = (
                item.get("id")
                or ""
            )

            summary = (
                summaries_zh.get(
                    sid
                )
                or
                summaries_en.get(
                    sid
                )
                or {}
            )

            if summary.get(
                "tldr"
            ):

                click.echo(
                    "    TL;DR: "
                    f"{summary['tldr']}"
                )

            tx = translations.get(
                sid
            )

            if (
                tx
                and tx.get(
                    "title_zh"
                )
            ):

                click.echo(
                    "    标题(中): "
                    f"{tx['title_zh']}"
                )

            click.echo("")

        json_path = save_json(
            items,
            out_dir,
        )

        md_path = save_markdown(
            items,
            out_dir,
            summaries_zh,
            summaries_en,
            lang=lang,
            translations=translations,
        )

        click.echo(
            f"Saved: {json_path}"
        )

        click.echo(
            f"Saved: {md_path}"
        )

        page_url = None
        site_generated = False

        try:

            from .sitegen import generate_site

            site_cfg = (
                raw_cfg.get(
                    "site"
                )
                or {}
            )

            sd = (
                site_dir
                or site_cfg.get(
                    "dir"
                )
            )

            if (
                sd
                and
                (
                    site_cfg.get(
                        "enabled",
                        False,
                    )
                    or site_dir
                    is not None
                )
            ):

                keep = int(
                    site_cfg.get(
                        "keep_runs",
                        60,
                    )
                )

                site_title = (
                    site_cfg.get(
                        "title",
                        "arXiv Results",
                    )
                )

                theme = (
                    site_cfg.get(
                        "theme",
                        "light",
                    )
                )

                accent = (
                    site_cfg.get(
                        "accent",
                        "#2563eb",
                    )
                )

                site_res = (
                    generate_site(
                        items=items,
                        summaries_zh=(
                            summaries_zh
                            or {}
                        ),
                        summaries_en=(
                            summaries_en
                            or {}
                        ),
                        translations=(
                            translations
                            or {}
                        ),
                        site_dir=sd,
                        site_title=site_title,
                        keep_runs=keep,
                        theme=theme,
                        accent=accent,
                    )
                )

                click.echo(
                    "Saved: "
                    f"{site_res['index_path']}"
                )

                page_url = (
                    site_url
                    or site_cfg.get(
                        "url"
                    )
                )

                if (
                    page_url
                    and not page_url.endswith(
                        "/"
                    )
                ):
                    page_url += "/"

                site_generated = True

        except Exception as exc:

            click.secho(
                "[Site] 生成失败: "
                f"{exc}",
                fg="red",
            )

        pdf_path = ""

        if pdf_enabled:

            try:

                pdf_path = (
                    md_to_pdf(
                        md_path
                    )
                )

                click.echo(
                    "Saved: "
                    f"{pdf_path}"
                )

            except Exception as exc:

                click.secho(
                    "[PDF] 生成失败: "
                    f"{exc}",
                    fg="red",
                )

        email_sent = False

        email_requested = (
            bool(
                email_cfg.get(
                    "enabled"
                )
            )
            and
            bool(items)
        )

        if (
            email_cfg.get(
                "enabled"
            )
            and not items
        ):

            click.echo(
                "[Email] 今日无新增"
                "相关论文，跳过发送。"
            )

        if email_requested:

            try:

                global _SENT_EMAIL

                if _SENT_EMAIL:

                    click.secho(
                        "[Email] 已在本进程"
                        "发送过，跳过",
                        fg="yellow",
                    )

                else:

                    try:

                        stamp = (
                            _extract_stamp_from_path(
                                json_path
                            )
                        )

                    except Exception:

                        stamp = (
                            os.path.splitext(
                                os.path.basename(
                                    json_path
                                    or ""
                                )
                            )[0]
                        )

                    flag_dir = pathlib.Path(
                        out_dir
                        or "outputs"
                    )

                    flag_dir.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    flag_path = (
                        flag_dir
                        /
                        f"email_sent_{stamp}.flag"
                    )

                    if flag_path.exists():

                        click.secho(
                            "[Email] "
                            f"本次快照({stamp})"
                            "已发送过，跳过",
                            fg="yellow",
                        )

                    else:

                        env_to = os.getenv(
                            "EMAIL_TO",
                            "",
                        )

                        if env_to:

                            to_list = [
                                x.strip()
                                for x in re.split(
                                    r"[;,]",
                                    env_to,
                                )
                                if x.strip()
                            ]

                        else:

                            to_list = (
                                email_cfg.get(
                                    "to"
                                )
                                or []
                            )

                        sender = (
                            os.getenv(
                                "EMAIL_SENDER",
                                "",
                            )
                            or
                            email_cfg.get(
                                "sender"
                            )
                            or ""
                        )

                        server = (
                            email_cfg.get(
                                "smtp_server"
                            )
                            or
                            "smtp.qq.com"
                        )

                        port = int(
                            email_cfg.get(
                                "smtp_port"
                            )
                            or 465
                        )

                        user = (
                            os.getenv(
                                "SMTP_USER",
                                "",
                            )
                            or
                            email_cfg.get(
                                "smtp_user"
                            )
                            or sender
                        )

                        pass_env = (
                            email_cfg.get(
                                "smtp_pass_env"
                            )
                            or
                            "SMTP_PASS"
                        )

                        passwd = os.getenv(
                            pass_env,
                            "",
                        )

                        subject = (
                            email_cfg.get(
                                "subject"
                            )
                            or
                            "[arXiv] Digest"
                        )

                        tls_mode = (
                            email_cfg.get(
                                "tls",
                                "auto",
                            )
                        )

                        debug = bool(
                            email_cfg.get(
                                "debug",
                                False,
                            )
                        )

                        detail = (
                            email_cfg.get(
                                "detail",
                                "full",
                            )
                        )

                        max_items = int(
                            email_cfg.get(
                                "max_items",
                                50,
                            )
                        )

                        to_list = (
                            _dedup_addrs(
                                to_list
                            )
                        )

                        if not (
                            to_list
                            and sender
                            and passwd
                        ):

                            click.secho(
                                "[Email] 配置不完整，"
                                "跳过发送",
                                fg="yellow",
                            )

                        else:

                            html_body = ""

                            if page_url:

                                html_body += (
                                    '<div style="margin-bottom:10px">'
                                    'Web 版：'
                                    f'<a href="{page_url}">'
                                    f'{page_url}'
                                    '</a></div>'
                                )

                            html_body += (
                                render_email_html(
                                    items=items,
                                    lang=lang,
                                    translations=(
                                        translations
                                    ),
                                    summaries_zh=(
                                        summaries_zh
                                    ),
                                    summaries_en=(
                                        summaries_en
                                    ),
                                    detail=detail,
                                    max_items=(
                                        max_items
                                    ),
                                    title=(
                                        subject.replace(
                                            "[arXiv]",
                                            "arXiv",
                                        )
                                    ),
                                )
                            )

                            from .mailer import send_email

                            attachments: List[
                                str
                            ] = []

                            if (
                                email_cfg.get(
                                    "attach_md",
                                    False,
                                )
                                and md_path
                            ):
                                attachments.append(
                                    md_path
                                )

                            if (
                                email_cfg.get(
                                    "attach_pdf",
                                    False,
                                )
                                and pdf_path
                            ):
                                attachments.append(
                                    pdf_path
                                )

                            click.echo(
                                "[Email] will send: "
                                f"detail={detail} "
                                f"to={len(to_list)} "
                                "recipient(s)"
                            )

                            send_email(
                                sender=sender,
                                to_list=to_list,
                                subject=subject,
                                html_body=html_body,
                                smtp_server=server,
                                smtp_port=port,
                                smtp_user=user,
                                smtp_pass=passwd,
                                tls_mode=tls_mode,
                                attachments=attachments,
                                debug=debug,
                                timeout=20,
                            )

                            _SENT_EMAIL = True
                            email_sent = True

                            try:
                                flag_path.touch()
                            except Exception:
                                pass

                            click.echo(
                                "[Email] 已发送"
                            )

            except Exception as exc:

                click.secho(
                    "[Email] 发送失败: "
                    f"{exc}",
                    fg="red",
                )

        should_mark_seen = False

        if items:

            if email_requested:
                should_mark_seen = (
                    email_sent
                )

            elif mark_seen_on_site:
                should_mark_seen = (
                    site_generated
                )

        try:

            if (
                unique_only
                and state_path
                and items
                and should_mark_seen
            ):

                all_seen = set(
                    seen_ids
                )

                for item in items:

                    key = (
                        _item_dedup_key(
                            item
                        )
                    )

                    if key:
                        all_seen.add(
                            key
                        )

                path = pathlib.Path(
                    state_path
                )

                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with open(
                    path,
                    "w",
                    encoding="utf-8",
                ) as f:

                    json.dump(
                        {
                            "ids": sorted(
                                all_seen
                            )
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

                click.echo(
                    "[Freshness] "
                    "更新去重状态，"
                    f"共 {len(all_seen)} 条 "
                    f"-> {state_path}"
                )

            elif (
                unique_only
                and items
                and
                not should_mark_seen
            ):

                click.echo(
                    "[Freshness] 本次未写入"
                    "去重状态：邮件未成功发送，"
                    "或当前运行未允许通过"
                    "站点标记 seen。"
                )

        except Exception as exc:

            click.secho(
                "[Freshness] "
                "保存去重状态失败: "
                f"{exc}",
                fg="yellow",
            )

        if verbose:

            click.echo(
                "[Run] Done"
            )

    except Exception as exc:

        click.secho(
            "[Run] ERROR: "
            f"{exc}",
            fg="red",
        )

        traceback.print_exc()

        sys.exit(1)


if __name__ == "__main__":
    cli()
