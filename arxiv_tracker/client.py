# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional

import requests

ARXIV_HTTPS = "https://export.arxiv.org/api/query"
ARXIV_HTTP = "http://export.arxiv.org/api/query"

DEFAULT_TIMEOUT = float(os.getenv("ARXIV_TIMEOUT", "45"))
MAX_ATTEMPTS = int(os.getenv("ARXIV_MAX_ATTEMPTS", "6"))
BASE_PAUSE = float(os.getenv("ARXIV_PAUSE", "1.5"))
MAX_SLEEP = float(os.getenv("ARXIV_MAX_SLEEP", "20"))

# arXiv recommends spacing repeated API calls by roughly 3 seconds.
MIN_REQUEST_INTERVAL = float(os.getenv("ARXIV_MIN_INTERVAL", "3.0"))

# Keep normal GET URLs small.  arXiv officially supports POST and recommends it
# when the parameter list is unusually long.
GET_URL_LIMIT = int(os.getenv("ARXIV_GET_URL_LIMIT", "1800"))

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
HEADERS = {
    "User-Agent": os.getenv(
        "ARXIV_UA",
        "arxiv-tracker/0.1 (+https://github.com/ag3070744531/Arxiv-tracker)",
    ),
    "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}

_session = requests.Session()
_last_request_at = 0.0


def _retry_after_seconds(response: Optional[requests.Response]) -> Optional[float]:
    if response is None:
        return None

    value = response.headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(
                0.0,
                (retry_at - datetime.now(timezone.utc)).total_seconds(),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def _sleep_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    backoff = min(
        BASE_PAUSE * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
        MAX_SLEEP,
    )
    delay = max(backoff, retry_after or 0.0)
    time.sleep(delay)
    return delay


def _respect_rate_limit() -> None:
    global _last_request_at

    now = time.monotonic()
    elapsed = now - _last_request_at
    if _last_request_at > 0 and elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    _last_request_at = time.monotonic()


def _prepared_get_url_length(base_url: str, params: Dict[str, str]) -> int:
    request = requests.Request("GET", base_url, params=params)
    prepared = request.prepare()
    return len(prepared.url or base_url)


def _do_request(
    base_url: str,
    params: Dict[str, str],
    *,
    timeout: Optional[float] = None,
    force_post: bool = False,
) -> requests.Response:
    """
    Request arXiv with retry/backoff.

    Short requests use GET.
    Long requests use POST so the search expression is not stuffed into the URL.
    """
    timeout = timeout or DEFAULT_TIMEOUT
    use_post = force_post or _prepared_get_url_length(base_url, params) > GET_URL_LIMIT

    last_err: Optional[Exception] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after: Optional[float] = None

        try:
            _respect_rate_limit()

            if use_post:
                resp = _session.post(
                    base_url,
                    data=params,
                    headers=HEADERS,
                    timeout=timeout,
                )
            else:
                resp = _session.get(
                    base_url,
                    params=params,
                    headers=HEADERS,
                    timeout=timeout,
                )

            if resp.status_code in RETRYABLE_STATUS:
                if resp.status_code == 429:
                    retry_after = _retry_after_seconds(resp)
                raise requests.exceptions.HTTPError(
                    f"HTTP {resp.status_code}",
                    response=resp,
                )

            # If a GET is rejected as 400, retry the same request once as POST.
            # This is especially useful for long/complex arXiv search expressions.
            if resp.status_code == 400 and not use_post:
                use_post = True
                last_err = requests.exceptions.HTTPError(
                    "HTTP 400 on GET; retrying as POST",
                    response=resp,
                )
                if attempt < MAX_ATTEMPTS:
                    continue

            return resp

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            last_err = exc

        except requests.exceptions.HTTPError as exc:
            last_err = exc
            status = getattr(exc.response, "status_code", None)
            if status not in RETRYABLE_STATUS:
                break

        if attempt < MAX_ATTEMPTS:
            delay = _sleep_backoff(attempt, retry_after=retry_after)
            status = getattr(
                getattr(last_err, "response", None),
                "status_code",
                None,
            )
            reason = f"HTTP {status}" if status else type(last_err).__name__
            print(
                f"[arXiv] {reason}; retry {attempt + 1}/{MAX_ATTEMPTS} "
                f"in {delay:.1f}s"
            )

    if last_err:
        raise last_err
    raise RuntimeError("Unknown arXiv request error.")


def fetch_arxiv_feed(
    query: str,
    start: int = 0,
    max_results: int = 10,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> str:
    """Fetch an arXiv Atom feed, preferring HTTPS and falling back to HTTP."""
    params: Dict[str, str] = {
        "search_query": query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }

    last_err: Optional[Exception] = None

    for base_url in (ARXIV_HTTPS, ARXIV_HTTP):
        try:
            response = _do_request(
                base_url,
                params,
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_err = exc
            continue

    assert last_err is not None
    raise last_err
