"""Verification script testing all web routes and API endpoints in a clean state."""
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)

def test_pages():
    routes = [
        "/",
        "/courses",
        "/ask",
        "/study",
    ]
    for r in routes:
        resp = client.get(r)
        assert resp.status_code == 200, f"Route {r} failed with status {resp.status_code}"
        print(f"PAGE OK: {r} (200)")

    documents = client.get("/api/documents").json()
    if documents:
        for indexed_doc in documents:
            chunks_response = client.get(f"/api/documents/{indexed_doc['doc_id']}/chunks")
            assert chunks_response.status_code == 200
            actual_chunks = chunks_response.json()
            assert len(actual_chunks) == indexed_doc["chunk_count"], (
                f"Index mismatch for {indexed_doc['filename']}: registry says "
                f"{indexed_doc['chunk_count']}, vector store has {len(actual_chunks)}"
            )
        print(f"INDEX OK: {len(documents)} document registry/vector counts match")

        doc = documents[0]
        resp = client.get(f"/viewer/{doc['doc_id']}?page=1")
        assert resp.status_code == 200, f"Document viewer failed with status {resp.status_code}"
        assert doc["filename"] in resp.text
        print(f"PAGE OK: /viewer/{doc['doc_id']} (200, live metadata)")

        resp = client.get(f"/api/documents/{doc['doc_id']}/pages/1")
        assert resp.status_code == 200, f"Document page API failed with status {resp.status_code}"
        assert resp.json()["total_pages"] == doc["page_count"]
        print(f"API OK: document page 1/{doc['page_count']}")

    assert client.get("/viewer/not-a-real-document").status_code == 404
    print("PAGE OK: missing viewer document returns 404")

def test_apis():
    api_routes = [
        ("/api/courses", 200),
        ("/api/documents", 200),
        ("/api/study/flashcards", 200),
        ("/api/study/flashcards/stats", 200),
        ("/api/study/quizzes", 200),
        ("/api/study/summaries", 200),
        ("/api/study/glossary", 200),
        ("/api/resources", 200),
        ("/api/analytics/dashboard", 401),
        ("/api/analytics/weak-areas", 401),
        ("/api/analytics/topics", 401),
        ("/api/analytics/activity", 401),
    ]
    for r, expected in api_routes:
        resp = client.get(r)
        assert resp.status_code == expected, f"API {r} returned {resp.status_code}"
        data = resp.json()
        print(f"API OK: {r} -> {len(data) if isinstance(data, list) else 'dict'}")

if __name__ == "__main__":
    test_pages()
    test_apis()
    print("ALL CLEAN STATE VERIFICATIONS PASSED!")
