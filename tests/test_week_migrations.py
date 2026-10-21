"""Existing uploads survive the additive week migration and default to general."""
import sqlite3

from archive import config, registry, resources


def test_legacy_document_and_resource_schemas_migrate_without_data_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(config,"DATA_DIR",tmp_path)
    monkeypatch.setattr(config,"REGISTRY_DB",tmp_path / "registry.sqlite")
    monkeypatch.setattr(config,"APP_DB",tmp_path / "app.sqlite")
    with sqlite3.connect(config.REGISTRY_DB) as con:
        con.executescript(registry._SCHEMA)
        con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)",
                    ("original","hash","Complete statistics textbook","STA 111","statistics.pdf","original.pdf",353,80,"2026-10-01"))
    with sqlite3.connect(config.APP_DB) as con:
        con.execute("""CREATE TABLE resources (id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,
                    course TEXT NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,video_id TEXT NOT NULL,created_at TEXT NOT NULL)""")
        con.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?)",
                    ("reference","Course handbook","Reference for the entire course","STA 111","link","https://example.org/handbook","","2026-10-01"))
    first = registry.get("original")
    assert first.week == 0 and first.page_count == 353 and first.chunk_count == 80
    assert resources.get_resource("reference")["week"] == 0
    # Repeated reads and writes must not reapply or break the migration.
    registry.add(first)
    assert registry.list_all("STA 111",0)[0].doc_id == "original"
    assert resources.list_resources("STA 111",0)[0]["title"] == "Course handbook"
    updated = resources.save_resource("Edited handbook","Still general","STA 111","link","https://example.org/handbook","reference")
    assert updated["week"] == 0
    assert updated["created_at"] == "2026-10-01"
