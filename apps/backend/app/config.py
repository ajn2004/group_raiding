from dotenv import load_dotenv
import os
from sqlalchemy.engine import URL
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
USERNAME = os.getenv("SQLALCHEMY_DATABASE_USER")
PASSWORD = os.getenv("SQLALCHEMY_DATABASE_PASSWORD")
DB_SERVER = str(os.getenv("SQLALCHEMY_DATABASE_HOST")) + ":" + str(os.getenv("SQLALCHEMY_DATABASE_PORT"))
DB_NAME = os.getenv("SQLALCHEMY_DATABASE_DB")


def database_url() -> URL:
    """Build the primary PostgreSQL URL without parsing credential characters."""
    missing = [name for name, value in (
        ("SQLALCHEMY_DATABASE_USER", USERNAME),
        ("SQLALCHEMY_DATABASE_PASSWORD", PASSWORD),
        ("SQLALCHEMY_DATABASE_HOST", os.getenv("SQLALCHEMY_DATABASE_HOST")),
        ("SQLALCHEMY_DATABASE_PORT", os.getenv("SQLALCHEMY_DATABASE_PORT")),
        ("SQLALCHEMY_DATABASE_DB", DB_NAME),
    ) if value is None or value == ""]
    if missing:
        raise RuntimeError("Missing database configuration: " + ", ".join(missing))
    return URL.create(
        "postgresql+psycopg2", username=USERNAME, password=PASSWORD,
        host=os.getenv("SQLALCHEMY_DATABASE_HOST"),
        port=int(os.getenv("SQLALCHEMY_DATABASE_PORT")), database=DB_NAME,
    )
WCL_CLIENT_ID = os.getenv("WCL_CLIENT_ID")
WCL_CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET")
