from archive.chunker import chunk_page
from archive.parser import Page


def _page(text, number=3):
    return Page(number=number, text=text, chapter="Ch 1")


def test_chunks_keep_page_number_and_chapter():
    chunks = chunk_page(_page("Gradient descent minimizes a loss. " * 80, number=7), size=400, overlap=50)
    assert len(chunks) > 1
    assert all(c.page == 7 and c.chapter == "Ch 1" for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunks_respect_size():
    chunks = chunk_page(_page("word " * 1000), size=300, overlap=40)
    assert all(len(c.text) <= 300 + 80 for c in chunks)   # tail fold may exceed slightly


def test_hyphenated_linebreaks_are_rejoined():
    chunks = chunk_page(_page("The optimi-\nzation step is important for training models today."))
    assert "optimization" in chunks[0].text


def test_empty_page_yields_no_chunks():
    assert chunk_page(_page("   \n\n  ")) == []
