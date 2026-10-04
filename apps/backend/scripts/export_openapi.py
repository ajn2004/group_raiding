"""Export the API OpenAPI document to the web workspace."""

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.main import app
from app.api.openapi import serialize_openapi

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "apps/web/src/lib/api/generated/openapi.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialize_openapi(app))


if __name__ == "__main__":
    main()
