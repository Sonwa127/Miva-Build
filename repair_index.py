"""Rebuild the current vector collection from registered source PDFs.

This is safe to rerun: document IDs are content hashes and chunk writes are upserts.
The previous versioned collection is left untouched for recovery.
"""
from __future__ import annotations

from pathlib import Path

from archive import courses, ingest, registry
from archive.store import VectorStore


def main() -> int:
    store = VectorStore()
    records = registry.list_all()
    known_courses = {course.code for course in courses.list_courses()}
    failures: list[str] = []

    print(f"Rebuilding {len(records)} registered document(s)...")
    for record in records:
        source = Path(record.path)
        if not source.is_file():
            failures.append(f"{record.filename}: source file is missing ({source})")
            continue

        result = ingest.ingest_pdf(source, store, course=record.course, force=True)
        if result.status != "ingested":
            failures.append(f"{record.filename}: {result.status} - {result.detail}")
            continue
        print(
            f"OK  {record.filename}: {result.pages} page(s), "
            f"{result.chunks} chunk(s), course={record.course or '<unassigned>'}"
        )

    orphan_courses = sorted({r.course for r in records if r.course and r.course not in known_courses})
    if orphan_courses:
        print("WARNING: Documents reference missing course codes: " + ", ".join(orphan_courses))

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Index rebuild complete: {store.count()} total chunk(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
