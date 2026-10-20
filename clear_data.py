"""Script to clear all mock data and reset the system to a clean state."""
import sqlite3
import shutil
from pathlib import Path

DATA_DIR = Path("data")

for db_name in ["app.sqlite", "registry.sqlite"]:
    db_file = DATA_DIR / db_name
    if db_file.exists():
        con = sqlite3.connect(db_file)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            cur.execute(f"DELETE FROM {t}")
            print(f"Cleared table: {db_name} -> {t}")
        con.commit()
        con.close()

# Clear ChromaDB persistent directory if it exists
chroma_dir = DATA_DIR / "chroma"
if chroma_dir.exists():
    try:
        shutil.rmtree(chroma_dir)
        print("Cleared ChromaDB store.")
    except Exception as e:
        print("Note on chroma removal:", e)

# Clear uploaded files
uploads_dir = DATA_DIR / "uploads"
if uploads_dir.exists():
    for f in uploads_dir.glob("*.pdf"):
        try:
            f.unlink()
            print(f"Removed uploaded file: {f.name}")
        except Exception as e:
            print("Note on file removal:", e)

print("All mock and persisted data cleared successfully!")
