from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def format_publisher_label(display_name: str | None, handle: str | None) -> str | None:
    """Human-readable publisher: ``Name (handle)`` when both differ, else whichever is set."""
    n = (display_name or "").strip()
    h = (handle or "").strip()
    if not n and not h:
        return None
    if n and h:
        if n.casefold() == h.casefold():
            return n
        return f"{n} ({h})"
    return n or h


@dataclass(frozen=True, slots=True)
class Release:
    project: str
    source: str
    artifact: str
    version: str
    url: str
    released_at: datetime
    github_repo: str | None = None
    description: str | None = None
    #: Comma-separated contributor names (or single label) when the source exposes them.
    publisher: str | None = None

    def as_markdown_line(self, *, omit_project: bool = False) -> str:
        date_value = self.released_at.date().isoformat()
        gh = f"`{self.github_repo}`" if self.github_repo else "—"
        pub = self.publisher if self.publisher else "—"
        if omit_project:
            header = (
                f"- {gh} | {self.source} | `{self.artifact}` | "
                f"`{self.version}` | {pub} | {date_value} | [link]({self.url})"
            )
        else:
            header = (
                f"- `{self.project}` | {gh} | {self.source} | `{self.artifact}` | "
                f"`{self.version}` | {pub} | {date_value} | [link]({self.url})"
            )
        if not self.description:
            return header
        return f"{header}\n  - Description: {self.description}"
