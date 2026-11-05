from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path = field(default_factory=lambda: ROOT / "data/pprouter.db")
    deepseek_api_key: str = ""
    moonshot_api_key: str = ""
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4000",
        "http://localhost:4000",
    )
    timeout_seconds: float = 180
    router_timeout_seconds: float = 5
    max_concurrent: int = 16
    cookie_secure: bool = False
    session_seconds: int = 8 * 3600
    max_body_bytes: int = 20 * 1024 * 1024

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path.resolve()}"

    def configured(self, provider: str) -> bool:
        return bool(self.deepseek_api_key if provider == "deepseek" else self.moonshot_api_key)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        path = Path(os.getenv("PPROUTER_DATABASE_PATH", "data/pprouter.db"))
        if not path.is_absolute():
            path = ROOT / path
        origins = os.getenv("PPROUTER_ALLOWED_ORIGINS", "")
        settings = cls(
            database_path=path,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            moonshot_api_key=os.getenv("MOONSHOT_API_KEY", "").strip(),
            allowed_origins=tuple(x.strip().rstrip("/") for x in origins.split(",") if x.strip())
            if origins
            else cls().allowed_origins,
            timeout_seconds=float(os.getenv("PPROUTER_TIMEOUT_SECONDS", "180")),
            router_timeout_seconds=float(os.getenv("PPROUTER_ROUTER_TIMEOUT_SECONDS", "5")),
            max_concurrent=int(os.getenv("PPROUTER_MAX_CONCURRENT", "16")),
            cookie_secure=os.getenv("PPROUTER_COOKIE_SECURE", "false").lower() == "true",
        )
        if "*" in settings.allowed_origins:
            raise ValueError("Use explicit allowed origins")
        if settings.timeout_seconds <= 0 or settings.router_timeout_seconds <= 0:
            raise ValueError("Timeouts must be positive")
        if settings.max_concurrent < 1:
            raise ValueError("Concurrency must be positive")
        return settings
