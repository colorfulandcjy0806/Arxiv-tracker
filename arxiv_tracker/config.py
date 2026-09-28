from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class Settings:
    # Core-track arXiv categories.
    categories: List[str] = field(default_factory=list)

    # Related-track categories. If empty, the CLI falls back to categories.
    related_categories: List[str] = field(default_factory=list)

    # Core track: Social Event Detection.
    keywords: List[str] = field(default_factory=list)

    # Related track:
    # 1) direct social-media/event phrases;
    # 2) broader methods;
    # 3) social-media context anchors;
    # 4) event/topic context anchors.
    related_keywords: List[str] = field(default_factory=list)
    related_method_keywords: List[str] = field(default_factory=list)
    related_social_context_keywords: List[str] = field(default_factory=list)
    related_event_context_keywords: List[str] = field(default_factory=list)

    # Legacy field kept for older configs. New configs should use the two
    # context lists above.
    related_context_keywords: List[str] = field(default_factory=list)

    exclude_keywords: List[str] = field(default_factory=list)

    # categories group vs core-keyword group.
    logic: str = "AND"

    # Final result caps (after semantic relevance filtering).
    max_results: int = 10
    core_max_results: int = 7
    related_max_results: int = 3

    sort_by: str = "submittedDate"
    sort_order: str = "descending"

    @classmethod
    def from_file(cls, path: str) -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        known = cls.__annotations__
        obj = cls(**{k: v for k, v in data.items() if k in known})

        # Backward compatibility for configs created before the social/event
        # context split. Treat the old related_context_keywords as social
        # anchors only when the new field is absent.
        if not obj.related_social_context_keywords and obj.related_context_keywords:
            obj.related_social_context_keywords = list(obj.related_context_keywords)

        if not obj.related_categories:
            obj.related_categories = list(obj.categories)

        return obj

    def merge_cli(
        self,
        categories=None,
        related_categories=None,
        keywords=None,
        related_keywords=None,
        related_method_keywords=None,
        related_social_context_keywords=None,
        related_event_context_keywords=None,
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
        if related_categories:
            self.related_categories = list(related_categories)
        if keywords:
            self.keywords = list(keywords)
        if related_keywords:
            self.related_keywords = list(related_keywords)
        if related_method_keywords:
            self.related_method_keywords = list(related_method_keywords)
        if related_social_context_keywords:
            self.related_social_context_keywords = list(
                related_social_context_keywords
            )
        elif related_context_keywords:
            # Legacy CLI option.
            self.related_social_context_keywords = list(related_context_keywords)
        if related_event_context_keywords:
            self.related_event_context_keywords = list(
                related_event_context_keywords
            )
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

        if not self.related_categories:
            self.related_categories = list(self.categories)

        return self
