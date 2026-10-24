"""Job-title filtering for contact discovery (requirement R3).

Two layers: a Forager boolean `role_title` query narrows the search server-side,
and `matches()` re-checks every result locally, because full-text search can be
loose and the exclude list must be enforced exactly.
"""

import re
from dataclasses import dataclass, field


@dataclass
class TitleFilter:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.include = [term.strip() for term in self.include if term and term.strip()]
        self.exclude = [term.strip() for term in self.exclude if term and term.strip()]
        self._include_patterns = [_word_pattern(term) for term in self.include]
        self._exclude_patterns = [_word_pattern(term) for term in self.exclude]

    def forager_query(self) -> str | None:
        """Boolean query for Forager's role_title, e.g. '"VP" OR "Head of Sales"'."""
        if not self.include:
            return None
        return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in self.include)

    def matches(self, title: str | None) -> bool:
        if self.include and not title:
            return False
        title = title or ""
        if any(pattern.search(title) for pattern in self._exclude_patterns):
            return False
        return not self._include_patterns or any(p.search(title) for p in self._include_patterns)

    def describe(self) -> str:
        return f"include: {', '.join(self.include) or 'any'}; exclude: {', '.join(self.exclude) or 'none'}"


def _word_pattern(term: str) -> re.Pattern:
    words = (re.escape(word) for word in term.replace('"', "").split())
    return re.compile(r"\b" + r"\s+".join(words) + r"\b", re.IGNORECASE)
