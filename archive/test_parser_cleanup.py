from archive.parser import Page, _clean_title, strip_running_headers

HEADER = "COS 101 - Practical Demos: Introduction to Computing Sciences"
WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


def _pages(n=8):
    return [Page(i, f"{HEADER}\nThis page explains the {WORDS[i - 1]} concept in detail.\nPage {i}", "")
            for i in range(1, n + 1)]


def test_repeated_header_and_footer_are_removed():
    cleaned = strip_running_headers(_pages())
    assert len(cleaned) == 8
    for p in cleaned:
        assert HEADER not in p.text
        assert "Page " not in p.text
        assert f"the {WORDS[p.number - 1]} concept" in p.text


def test_page_numbers_are_kept():
    assert [p.number for p in strip_running_headers(_pages())] == list(range(1, 9))


def test_header_text_in_the_middle_of_a_page_is_kept():
    pages = []
    for i in range(1, 9):
        w = WORDS[i - 1]
        lines = [HEADER, f"intro {w}", f"setup {w}", f"point {w}", HEADER,
                 f"detail {w}", f"more {w}", f"end {w}", f"Page {i}"]
        pages.append(Page(i, "\n".join(lines), ""))
    cleaned = strip_running_headers(pages)
    assert all(p.text.count(HEADER) == 1 for p in cleaned)    # only the middle copy survives


def test_short_documents_are_left_alone():
    pages = _pages(3)
    assert strip_running_headers(pages) == pages


def test_title_extension_is_removed():
    assert _clean_title("COS 101 - Practical Demos .docx") == "COS 101 - Practical Demos"
    assert _clean_title("Lab Manual.PDF") == "Lab Manual"
    assert _clean_title("Intro to Computing") == "Intro to Computing"
