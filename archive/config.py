"""Central settings for the archive. Override with environment variables."""
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("ARCHIVE_DATA_DIR", "data")).resolve()
CHROMA_DIR = DATA_DIR / "chroma"
REGISTRY_DB = DATA_DIR / "registry.sqlite"

COLLECTION_NAME = "course_chunks"

# Chunking: chunks never cross a page boundary, so every chunk maps to exactly
# one page and page-level citations are always exact.
CHUNK_CHARS = int(os.getenv("ARCHIVE_CHUNK_CHARS", "900"))
CHUNK_OVERLAP = int(os.getenv("ARCHIVE_CHUNK_OVERLAP", "150"))
MIN_CHUNK_CHARS = 80

# Pages with fewer characters than this are treated as scanned and sent to OCR.
OCR_MIN_CHARS = 40
ENABLE_OCR = os.getenv("ARCHIVE_ENABLE_OCR", "0") == "1"
