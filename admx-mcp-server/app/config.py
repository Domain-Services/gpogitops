"""Configuration and environment settings."""

import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # Database path
    db_path: Path | None

    # Server settings
    server_name: str = "admx-policy-server"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        env_path = os.environ.get("ADMX_DB_PATH")
        db_path = Path(env_path) if env_path else None

        return cls(db_path=db_path)

    def get_db_path(self) -> Path:
        """Get the path to the ADMX dictionary JSON file."""
        if self.db_path:
            return self.db_path

        # Try relative to app directory
        app_dir = Path(__file__).parent
        default_path = app_dir.parent.parent / "ms-admx-dictionary.json"

        if default_path.exists():
            return default_path

        # Try current directory
        cwd_path = Path.cwd() / "ms-admx-dictionary.json"
        if cwd_path.exists():
            return cwd_path

        return default_path


# Global settings instance
settings = Settings.from_env()
