"""Command line interface for the archive.

    python cli.py ingest ./pdfs --course "AI Fundamentals"
    python cli.py list
    python cli.py search "what is gradient descent" -k 5
    python cli.py remove <doc_id>
"""
import argparse
import sys
from pathlib import Path

from archive import registry
from archive.ingest import ingest_path
from archive.store import VectorStore


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="course-archive")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ingest", help="ingest a PDF or a folder of PDFs")
    a.add_argument("path")
    a.add_argument("--course", default="")
    a.add_argument("--force", action="store_true", help="re-ingest even if unchanged")
    a.add_argument("--ocr", action="store_true", help="OCR pages with no text layer")

    l = sub.add_parser("list", help="list ingested documents")
    l.add_argument("--course")

    s = sub.add_parser("search", help="semantic search with page citations")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--course")
    s.add_argument("--doc")

    c = sub.add_parser("chunks", help="print stored chunks of a document")
    c.add_argument("doc_id")
    c.add_argument("--page", type=int)
    c.add_argument("--limit", type=int, default=20)

    x = sub.add_parser("export", help="export all chunks of a document to CSV")
    x.add_argument("doc_id")
    x.add_argument("out", nargs="?", default=None)

    r = sub.add_parser("remove", help="remove a document by id")
    r.add_argument("doc_id")

    args = p.parse_args(argv)

    if args.cmd == "ingest":
        store = VectorStore()
        results = ingest_path(Path(args.path), store, args.course, args.force, args.ocr or None)
        for res in results:
            extra = f"{res.pages} pages, {res.chunks} chunks" if res.status == "ingested" else res.detail
            print(f"{res.status:9} {res.path.name}  {extra}")
        return 1 if any(r.status == "failed" for r in results) else 0

    if args.cmd == "list":
        docs = registry.list_all(args.course)
        if not docs:
            print("Archive is empty.")
        for d in docs:
            print(f"{d.doc_id}  {d.course or '-':20} {d.title}  ({d.page_count} pages, {d.chunk_count} chunks)")
        return 0

    if args.cmd == "search":
        store = VectorStore()
        hits = store.search(args.query, args.k, args.course, args.doc)
        if not hits:
            print("No results.")
        for i, h in enumerate(hits, 1):
            snippet = " ".join(h.text.split())[:240]
            chap = f" | {h.chapter}" if h.chapter else ""
            print(f"{i}. {h.citation}{chap}  score={h.score:.2f}\n   {snippet}\n")
        return 0

    if args.cmd == "chunks":
        rows = VectorStore().list_chunks(args.doc_id, args.page)
        if not rows:
            print("No chunks found. Check the doc id with: python cli.py list")
            return 1
        print(f"{len(rows)} chunks (showing up to {args.limit})\n")
        for page, idx, chapter, text in rows[: args.limit]:
            print(f"--- page {page}, chunk {idx}" + (f", {chapter}" if chapter else "") + " ---")
            print(text, "\n")
        return 0

    if args.cmd == "export":
        import csv
        rows = VectorStore().list_chunks(args.doc_id)
        if not rows:
            print("No chunks found. Check the doc id with: python cli.py list")
            return 1
        out = Path(args.out or f"{args.doc_id}_chunks.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig so Excel reads it correctly
            w = csv.writer(f)
            w.writerow(["page", "chunk", "chapter", "text"])
            w.writerows(rows)
        print(f"Wrote {len(rows)} chunks to {out.resolve()}")
        return 0

    if args.cmd == "remove":
        store = VectorStore()
        store.delete_doc(args.doc_id)
        ok = registry.remove(args.doc_id)
        print("Removed." if ok else "No such document id.")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
