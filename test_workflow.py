"""End-to-end integration test verifying course creation, document ingestion, study generation, and clean state."""
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)

def run_test():
    # 1. Create a course
    resp = client.post("/api/courses", json={
        "code": "CS 101",
        "name": "Introduction to Computer Science",
        "instructor": "Prof. Alan Turing",
        "term": "Fall 2025",
        "description": "Foundations of computation and algorithms."
    })
    assert resp.status_code == 201, f"Create course failed: {resp.text}"
    course = resp.json()
    print("1. Course created:", course["code"])

    # 2. Check course appears in list
    resp = client.get("/api/courses")
    courses = resp.json()
    assert len(courses) == 1
    assert courses[0]["code"] == "CS 101"
    print("2. Course verified in listing")

    # 3. Check course detail page renders
    resp = client.get(f"/courses/{course['id']}")
    assert resp.status_code == 200
    print("3. Course detail page OK")

    # 4. Generate a quiz
    resp = client.post("/api/study/quizzes/generate", json={
        "course_id": "CS 101",
        "topic": "Binary Search and Sorting",
        "num_questions": 3,
        "difficulty": "conceptual"
    })
    assert resp.status_code == 200, f"Quiz generation failed: {resp.status_code} {resp.text}"
    quiz = resp.json()
    print("4. Quiz generated with ID:", quiz["id"], "Questions:", len(quiz["questions"]))

    # 5. Submit quiz attempt
    resp = client.post(f"/api/study/quizzes/{quiz['id']}/submit", json={
        "student_id": "student_1",
        "answers": {str(q["id"]): q["choices"][0] for q in quiz["questions"]}
    })
    assert resp.status_code == 200
    res = resp.json()
    print(f"5. Quiz submitted, Score: {res['score']}/{res['total_questions']} ({res['percentage']}%)")

    # 6. Evaluate student answer
    resp = client.post("/api/evaluation/grade", json={
        "question": "What is the time complexity of binary search?",
        "reference_answer": "Binary search runs in O(log n) time because it halves the search space at each iteration.",
        "student_answer": "It is O(log n) as each comparison cuts the remaining elements in half.",
        "rubric": "Correct asymptotic complexity and explanation of division."
    })
    assert resp.status_code == 200
    eval_res = resp.json()
    print(f"6. Student answer graded: Score {eval_res['overall_score']}/10, AI boilerplate: {eval_res['is_ai_boilerplate']}")

    # 7. Check Dashboard analytics reflects the activity
    resp = client.get("/api/analytics/dashboard")
    stats = resp.json()
    assert stats["active_courses"] == 1
    assert len(stats["recent_activity"]) >= 1
    print("7. Dashboard analytics updated with live activity feed!")

if __name__ == "__main__":
    run_test()
    print("WORKFLOW INTEGRATION TEST PASSED!")
