import os
from dataclasses import dataclass
from .security import SessionCipher

@dataclass
class Settings:
    bot_token: str
    api_id: int
    api_hash: str
    owner_id: int
    encryption_key: str
    database_url: str
    timezone: str = "Asia/Baghdad"
    cipher: object = None

def load_settings() -> Settings:
    required = ["BOT_TOKEN", "API_ID", "API_HASH", "OWNER_ID", "SESSION_ENCRYPTION_KEY"]
    missing = [x for x in required if not os.getenv(x)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/publisher.db")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return Settings(
        bot_token=os.environ["BOT_TOKEN"],
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        owner_id=int(os.environ["OWNER_ID"]),
        encryption_key=os.environ["SESSION_ENCRYPTION_KEY"],
        database_url=url,
        timezone=os.getenv("TIMEZONE", "Asia/Baghdad"),
    )
