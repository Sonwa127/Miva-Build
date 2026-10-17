"""Central settings for the archive. Override with environment variables."""
import os
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Tiny .env reader for KEY=VALUE lines. Variables already set in the environment win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


# Secrets such as API keys live in a private .env file next to cli.py (never committed).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATA_DIR = Path(os.getenv("ARCHIVE_DATA_DIR", "data")).resolve()
CHROMA_DIR = DATA_DIR / "chroma"
REGISTRY_DB = DATA_DIR / "registry.sqlite"
USERS_DB = DATA_DIR / "users.sqlite"

COLLECTION_NAME = "course_chunks"

# Chunking: chunks never cross a page boundary, so every chunk maps to exactly
# one page and page-level citations are always exact.
CHUNK_CHARS = int(os.getenv("ARCHIVE_CHUNK_CHARS", "900"))
CHUNK_OVERLAP = int(os.getenv("ARCHIVE_CHUNK_OVERLAP", "150"))
MIN_CHUNK_CHARS = 80

# Pages with fewer characters than this are treated as scanned and sent to OCR.
OCR_MIN_CHARS = 40
ENABLE_OCR = os.getenv("ARCHIVE_ENABLE_OCR", "0") == "1"

# Question answering
LLM_PROVIDER = os.getenv("ARCHIVE_LLM_PROVIDER", "mistral")   # mistral, openai or ollama
LLM_MODEL = os.getenv("ARCHIVE_LLM_MODEL", "")                # empty = the provider's default
ANSWER_CHUNKS = int(os.getenv("ARCHIVE_ANSWER_CHUNKS", "6"))  # excerpts sent to the model
# If the best search match scores below this, we do not call the model at all.
# Tune it with real questions: raise it if off-topic questions still get answers.
MIN_SCORE = float(os.getenv("ARCHIVE_MIN_SCORE", "0.30"))
