"""Provider parsing must preserve playlists and privacy tokens without fetching URLs."""
from urllib.parse import parse_qs, urlsplit

import pytest

from archive.media import resolve_media


PLAYLIST = "PL1234567890abcdefghij"


@pytest.mark.parametrize("url,kind,provider,is_playlist,expected_embed", [
    (f"https://youtube.com/playlist?list={PLAYLIST}", "youtube_playlist", "YouTube", True, "/embed/videoseries?"),
    (f"https://www.youtube-nocookie.com/embed/videoseries?list={PLAYLIST}", "youtube_playlist", "YouTube", True, "/embed/videoseries?"),
    (f"https://youtube.com/embed?listType=playlist&list={PLAYLIST}", "youtube_playlist", "YouTube", True, "/embed/videoseries?"),
    (f"https://youtube.com/watch?v=dQw4w9WgXcQ&list={PLAYLIST}&index=3", "youtube_playlist", "YouTube", True, "/embed/dQw4w9WgXcQ?"),
    (f"https://youtu.be/dQw4w9WgXcQ?list={PLAYLIST}", "youtube_playlist", "YouTube", True, "/embed/dQw4w9WgXcQ?"),
    ("https://vimeo.com/76979871", "vimeo", "Vimeo", False, "https://player.vimeo.com/video/76979871?"),
    ("https://player.vimeo.com/video/76979871?h=abc123def0", "vimeo", "Vimeo", False, "h=abc123def0&dnt=1"),
    ("https://vimeo.com/76979871/abc123def0", "vimeo", "Vimeo", False, "h=abc123def0&dnt=1"),
    ("https://vimeo.com/channels/staffpicks/76979871", "vimeo", "Vimeo", False, "/video/76979871?"),
    ("https://vimeo.com/groups/education/videos/76979871", "vimeo", "Vimeo", False, "/video/76979871?"),
    ("https://vimeo.com/showcase/5376202", "vimeo_showcase", "Vimeo", True, "https://vimeo.com/album/5376202/embed"),
    ("https://vimeo.com/album/5376202/embed", "vimeo_showcase", "Vimeo", True, "https://vimeo.com/album/5376202/embed"),
    ("https://vimeo.com/showcase/5376202/embed", "vimeo_showcase", "Vimeo", True, "https://vimeo.com/album/5376202/embed"),
    ("https://www.loom.com/share/e5b8c04bca094dd8a5507925ab887002", "loom", "Loom", False, "https://www.loom.com/embed/e5b8c04bca094dd8a5507925ab887002"),
    ("https://geo.dailymotion.com/player/x8lr5.html?playlist=x5zhzj", "dailymotion_playlist", "Dailymotion", True, "playlist=x5zhzj"),
    ("https://geo.dailymotion.com/player/x8lr5.html?video=x84sh87&playlist=x5zhzj", "dailymotion_playlist", "Dailymotion", True, "video=x84sh87&playlist=x5zhzj"),
    ("https://geo.dailymotion.com/player/x8lr5.html?video=x84sh87", "dailymotion", "Dailymotion", False, "video=x84sh87"),
    ("https://cdn.example.org/lecture.mp4?signature=abc123", "video_file", "Video file", False, ".mp4?signature=abc123"),
    ("https://cdn.example.org/lecture.WEBM", "video_file", "Video file", False, ".WEBM"),
])
def test_media_formats_and_canonical_roundtrip(url, kind, provider, is_playlist, expected_embed):
    media = resolve_media(url)
    assert media.kind == kind
    assert media.provider == provider
    assert media.is_playlist is is_playlist
    assert expected_embed in media.embed_url
    assert resolve_media(media.url, media.kind) == media


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
    "https://vimeo.com.evil.example/76979871", "https://player.vimeo.com@evil.example/76979871",
    "https://www.youtube.com:9000/playlist?list=PL1234567890",
    "https://vimeo.com/76979871?h=abc<script>", "https://vimeo.com/76979871/abc123def0?h=different123",
    "https://www.loom.com/share/not-a-recording", "https://youtube.com/@channel",
    "https://youtube.com/playlist?list=bad", "https://youtube.com/watch?v=bad&list=PL1234567890",
    "https://geo.dailymotion.com/player/bad%22.html?playlist=x5zhzj",
    "https://geo.dailymotion.com/player/x8lr5.html?playlist=bad<script>",
    "http://cdn.example.org/lecture.mp4", "https://example.org/arbitrary/embed",
    "https://youtube.com\\@evil.example/watch?v=dQw4w9WgXcQ", "https://vimeo.com/76979871\nmalicious",
])
def test_invalid_player_sources_rejected(url):
    with pytest.raises(ValueError):
        resolve_media(url)


def test_playlist_selection_and_tracking_parameters():
    media = resolve_media(f"https://youtube.com/watch?v=dQw4w9WgXcQ&list={PLAYLIST}&index=3&si=tracking&autoplay=1")
    params = parse_qs(urlsplit(media.embed_url).query)
    assert params["list"] == [PLAYLIST]
    assert params["listType"] == ["playlist"]
    assert params["index"] == ["3"]
    assert "autoplay" not in params
    assert "si" not in params


def test_dailymotion_regular_links_require_real_player_id(monkeypatch):
    monkeypatch.delenv("ARCHIVE_DAILYMOTION_PLAYER_ID", raising=False)
    with pytest.raises(ValueError, match="Player ID"):
        resolve_media("https://dailymotion.com/playlist/x5zhzj")
    monkeypatch.setenv("ARCHIVE_DAILYMOTION_PLAYER_ID", "x8lr5")
    media = resolve_media("https://dailymotion.com/playlist/x5zhzj")
    assert media.embed_url == "https://geo.dailymotion.com/player/x8lr5.html?playlist=x5zhzj"
    monkeypatch.delenv("ARCHIVE_DAILYMOTION_PLAYER_ID")
    assert resolve_media(media.url, media.kind) == media


def test_unsupported_websites_can_be_kept_as_links():
    media = resolve_media("https://example.org/my-course", "link")
    assert media.kind == "link"
    assert not media.embed_url
    assert not media.is_playlist


def test_explicit_provider_cannot_be_spoofed():
    with pytest.raises(ValueError, match="YouTube"):
        resolve_media("https://vimeo.com/76979871", "youtube")
