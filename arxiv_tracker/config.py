from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from typing import List

@dataclass
class Settings:
    categories: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    logic: str = "AND"  # AND / OR
    max_results: int = 10
    sort_by: str = "submittedDate"    # submittedDate / lastUpdatedDate
    sort_order: str = "descending"    # ascending / descending

    @classmethod
    def from_file(cls, path: str) -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

    def merge_cli(
        self,
        categories=None,
        keywords=None,
        exclude_keywords=None,
        logic=None,
        max_results=None,
        sort_by=None,
        sort_order=None,
    ) -> "Settings":
        if categories: self.categories = list(categories)
        if keywords: self.keywords = list(keywords)
        if exclude_keywords: self.exclude_keywords = list(exclude_keywords)
        if logic: self.logic = logic
        if max_results is not None: self.max_results = int(max_results)
        if sort_by: self.sort_by = sort_by
        if sort_order: self.sort_order = sort_order
        return self
