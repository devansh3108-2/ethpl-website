from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    content_dir: Path

    @property
    def blog_dir(self) -> Path:
        return self.content_dir / "blog"

    @property
    def destinations_dir(self) -> Path:
        return self.content_dir / "destinations"

    @property
    def site_json_path(self) -> Path:
        return self.content_dir / "site.json"
