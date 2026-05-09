from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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

    def as_markdown_line(self, *, omit_project: bool = False) -> str:
        date_value = self.released_at.date().isoformat()
        gh = f"`{self.github_repo}`" if self.github_repo else "—"
        if omit_project:
            header = (
                f"- {gh} | {self.source} | `{self.artifact}` | "
                f"`{self.version}` | {date_value} | [link]({self.url})"
            )
        else:
            header = (
                f"- `{self.project}` | {gh} | {self.source} | `{self.artifact}` | "
                f"`{self.version}` | {date_value} | [link]({self.url})"
            )
        if not self.description:
            return header
        return f"{header}\n  - Description: {self.description}"
