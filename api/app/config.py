from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    replicate_api_token: str | None
    api_port: int = 8000
    web_port: int = 5173

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("CANVAS_DATA_DIR", "./data"))
        database_path = Path(os.getenv("CANVAS_DATABASE_PATH", str(data_dir / "canvas.sqlite3")))
        return cls(
            data_dir=data_dir,
            database_path=database_path,
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN") or None,
            api_port=int(os.getenv("API_PORT", "8000")),
            web_port=int(os.getenv("WEB_PORT", "5173")),
        )
