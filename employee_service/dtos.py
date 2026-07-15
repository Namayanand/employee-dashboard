"""Plain dataclasses for data crossing the service boundary. Kept dependency-free
(no pydantic) so the service layer stays framework-agnostic; validation can be
added at the API/UI edge later."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageResult:
    """One page of employees plus the metadata a UI needs to render pagination."""
    items: list[dict]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if not self.page_size:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
