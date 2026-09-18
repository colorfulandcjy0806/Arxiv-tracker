from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class Settings:
    # arXiv categories
    categories: List[str] = field(default_factory=list)

    # Core track: Social Event Detection
    keywords: List[str] = field(default_factory=list)

    # Related track:
    # 1) directly related event/topic papers
    related_keywords: List[str] = field(default_factory=list)
    # 2) broader methods, but only when paired with related_context_keywords
    related_method_keywords: List[str] = field(default_factory=list)
    related_context_keywords: List[str] = field(default_factory=list)

    exclude_keywords: List[str] = field(default_factory=list)

    # categories group vs core keywords group
    logic: str = "AND"

    # Total cap and per-track caps
    max_results: int = 10
    core_max_results: int = 7
    related_max_results: int = 3

    # submittedDate is recommended for a daily-new-paper tracker
    sort_by: str = "submittedDate"
    sort_order: str = "descending"

    @classmethod
    def from_file(cls, path: str) -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        known = cls.__annotations__
        return cls(**{k: v for k, v in data.items() if k in known})

    def merge_cli(
        self,
        categories=None,
        keywords=None,
        related_keywords=None,
        related_method_keywords=None,
        related_context_keywords=None,
        exclude_keywords=None,
        logic=None,
        max_results=None,
        core_max_results=None,
        related_max_results=None,
        sort_by=None,
        sort_order=None,
    ) -> "Settings":
        if categories:
            self.categories = list(categories)
        if keywords:
            self.keywords = list(keywords)
        if related_keywords:
            self.related_keywords = list(related_keywords)
        if related_method_keywords:
            self.related_method_keywords = list(related_method_keywords)
        if related_context_keywords:
            self.related_context_keywords = list(related_context_keywords)
        if exclude_keywords:
            self.exclude_keywords = list(exclude_keywords)
        if logic:
            self.logic = logic
        if max_results is not None:
            self.max_results = int(max_results)
        if core_max_results is not None:
            self.core_max_results = int(core_max_results)
        if related_max_results is not None:
            self.related_max_results = int(related_max_results)
        if sort_by:
            self.sort_by = sort_by
        if sort_order:
            self.sort_order = sort_order
        return self
