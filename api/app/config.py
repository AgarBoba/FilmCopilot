from dataclasses import dataclass
from pathlib import Path
import os

# Project root: api/app/config.py -> api/app -> api -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(value: str | Path) -> Path:
    """Resolve a relative path against the project root, not the process cwd.

    The API runs from ``api/`` while the Worker runs from the project root, so
    cwd-relative paths made them open different databases and asset folders.
    """
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    replicate_api_token: str | None = None
    api_port: int = 8000
    web_port: int = 5173

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = resolve_project_path(os.getenv("CANVAS_DATA_DIR", "./data"))
        database_path = resolve_project_path(
            os.getenv("CANVAS_DATABASE_PATH", str(data_dir / "canvas.sqlite3"))
        )
        return cls(
            data_dir=data_dir,
            database_path=database_path,
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN") or None,
            api_port=int(os.getenv("API_PORT", "8000")),
            web_port=int(os.getenv("WEB_PORT", "5173")),
        )
