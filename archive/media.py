"""Convert supported public media links into safe, provider-owned players.

No remote URLs are fetched and arbitrary embed HTML is never accepted.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit


VIDEO_KINDS = frozenset({"video", "youtube", "youtube_playlist", "vimeo", "vimeo_showcase", "loom", "dailymotion", "dailymotion_playlist", "video_file"})


@dataclass(frozen=True)
class MediaLink:
    url: str
    kind: str
    video_id: str = ""
    provider: str = "Website"
    embed_url: str = ""
    is_playlist: bool = False
    player_type: str = "iframe"


def resolve_media(url: str, kind: str = "video") -> MediaLink:
    url = url.strip()
    if len(url) > 2048 or any(ord(character) < 33 for character in url) or "\\" in url:
        raise ValueError("Use a complete URL without spaces, backslashes, or control characters.")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = (parts.hostname or "").lower()
    except ValueError as error:
        raise ValueError("The resource URL is invalid.") from error
    if parts.scheme not in {"http", "https"} or not host or parts.username is not None or parts.password is not None:
        raise ValueError("Use a complete http:// or https:// link without embedded credentials.")
    if kind == "link":
        return MediaLink(url, "link")
    if kind not in VIDEO_KINDS:
        raise ValueError("Choose a video / playlist or a useful link.")
    if port not in {None, 80 if parts.scheme == "http" else 443}:
        raise ValueError("Video player URLs must use the provider's standard port.")

    segments = parts.path.strip("/").split("/")
    query = parse_qs(parts.query)
    result: MediaLink | None = None
    if host in {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        result = _youtube(host, segments, query)
    elif host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        result = _vimeo(segments, query)
    elif host in {"loom.com", "www.loom.com"}:
        if len(segments) == 2 and segments[0] in {"share", "embed"} and re.fullmatch(r"[a-fA-F0-9]{32}", segments[1]):
            video_id = segments[1].lower()
            result = MediaLink(f"https://www.loom.com/share/{video_id}", "loom", video_id, "Loom", f"https://www.loom.com/embed/{video_id}")
        else:
            raise ValueError("Paste a Loom recording's share or embed link.")
    elif host in {"dailymotion.com", "www.dailymotion.com", "geo.dailymotion.com", "dai.ly"}:
        result = _dailymotion(host, segments, query)
    elif parts.path.lower().endswith((".mp4", ".webm", ".ogv", ".ogg", ".m4v")):
        if parts.scheme != "https":
            raise ValueError("Use an HTTPS link for a direct video file.")
        result = MediaLink(url, "video_file", provider="Video file", embed_url=url, player_type="file")

    if result is None:
        raise ValueError("Use a YouTube video or playlist, Vimeo video or showcase, Loom recording, Dailymotion embed, or HTTPS MP4/WebM video. Other websites can be added as Useful links.")
    # Legacy API callers can still explicitly require a particular provider.
    expected_provider = {"youtube":"YouTube", "youtube_playlist":"YouTube", "vimeo":"Vimeo", "vimeo_showcase":"Vimeo", "loom":"Loom", "dailymotion":"Dailymotion", "dailymotion_playlist":"Dailymotion", "video_file":"Video file"}.get(kind)
    if expected_provider and result.provider != expected_provider:
        raise ValueError(f"This resource type requires a {expected_provider} link. Choose Video / playlist for automatic detection.")
    return result


def _youtube(host: str, segments: list[str], query: dict) -> MediaLink:
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"} and len(segments) == 1:
        video_id = segments[0]
    elif segments == ["watch"]:
        video_id = query.get("v", [""])[0]
    elif len(segments) == 2 and segments[0] in {"embed", "shorts", "live"}:
        video_id = "" if segments[1] == "videoseries" else segments[1]
    elif segments not in (["playlist"], ["embed"]):
        raise ValueError("Paste a YouTube video or playlist link, not a channel or search page.")
    if video_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("The YouTube video ID is invalid.")
    playlist_id = query.get("list", [""])[0]
    if playlist_id and not re.fullmatch(r"[A-Za-z0-9_-]{10,150}", playlist_id):
        raise ValueError("The YouTube playlist ID is invalid.")
    if not video_id and not playlist_id:
        raise ValueError("The YouTube link needs a valid video or playlist ID.")
    playback = {"playsinline": "1", "rel": "0"}
    canonical = {}
    if video_id:
        canonical["v"] = video_id
    if playlist_id:
        canonical["list"] = playlist_id
        playback.update({"listType":"playlist", "list":playlist_id})
        index = query.get("index", [""])[0]
        if index.isascii() and index.isdigit() and 1 <= int(index) <= 10000:
            canonical["index"] = index
            playback["index"] = index
    path = "watch" if video_id else "playlist"
    embed_path = video_id or "videoseries"
    return MediaLink(f"https://www.youtube.com/{path}?{urlencode(canonical)}", "youtube_playlist" if playlist_id else "youtube", video_id, "YouTube", f"https://www.youtube-nocookie.com/embed/{embed_path}?{urlencode(playback)}", bool(playlist_id))


def _vimeo(segments: list[str], query: dict) -> MediaLink:
    if len(segments) in {2, 3} and segments[0] in {"showcase", "album"} and re.fullmatch(r"[0-9]{1,20}", segments[1]) and (len(segments) == 2 or segments[2] == "embed"):
        showcase_id = segments[1]
        return MediaLink(f"https://vimeo.com/showcase/{showcase_id}", "vimeo_showcase", showcase_id, "Vimeo", f"https://vimeo.com/album/{showcase_id}/embed", True)
    video_id = ""
    privacy_hash = query.get("h", [""])[0]
    if len(segments) in {1, 2} and re.fullmatch(r"[0-9]{1,20}", segments[0]):
        video_id = segments[0]
        if len(segments) == 2:
            if privacy_hash and privacy_hash != segments[1]:
                raise ValueError("The Vimeo link contains conflicting privacy hashes.")
            privacy_hash = segments[1]
    elif len(segments) == 2 and segments[0] == "video":
        video_id = segments[1]
    elif len(segments) == 3 and segments[0] == "channels":
        video_id = segments[2]
    elif len(segments) == 4 and segments[0] == "groups" and segments[2] == "videos":
        video_id = segments[3]
    if not re.fullmatch(r"[0-9]{1,20}", video_id):
        raise ValueError("Paste a Vimeo video or showcase (playlist) link.")
    if privacy_hash and not re.fullmatch(r"[A-Za-z0-9]{6,64}", privacy_hash):
        raise ValueError("The Vimeo privacy hash is invalid. Paste the original share link.")
    canonical = f"https://vimeo.com/{video_id}" + (f"/{privacy_hash}" if privacy_hash else "")
    parameters = {"h":privacy_hash} if privacy_hash else {}
    parameters["dnt"] = "1"
    return MediaLink(canonical, "vimeo", video_id, "Vimeo", f"https://player.vimeo.com/video/{video_id}?{urlencode(parameters)}")


def _dailymotion(host: str, segments: list[str], query: dict) -> MediaLink:
    player_id = os.getenv("ARCHIVE_DAILYMOTION_PLAYER_ID", "").strip()
    video_id = ""
    playlist_id = ""
    if host == "geo.dailymotion.com" and len(segments) == 2 and segments[0] == "player" and segments[1].endswith(".html"):
        player_id = segments[1][:-5]
        video_id = query.get("video", [""])[0]
        playlist_id = query.get("playlist", [""])[0]
    elif host == "dai.ly" and len(segments) == 1:
        video_id = segments[0]
    elif len(segments) == 2 and segments[0] in {"video", "playlist"}:
        if segments[0] == "video":
            video_id = segments[1].split("_", 1)[0]
        else:
            playlist_id = segments[1]
    else:
        raise ValueError("Use a Dailymotion video, playlist, or geo.dailymotion.com player embed link.")
    if not (video_id or playlist_id) or any(value and not re.fullmatch(r"[A-Za-z0-9]{2,64}", value) for value in (video_id, playlist_id)):
        raise ValueError("The Dailymotion video or playlist ID is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9]{3,32}", player_id):
        raise ValueError("Dailymotion requires a Player ID. Paste the full geo.dailymotion.com/player/PLAYER_ID.html embed URL, or configure ARCHIVE_DAILYMOTION_PLAYER_ID on the server. You can also save it as a Useful link.")
    parameters = {}
    if video_id:
        parameters["video"] = video_id
    if playlist_id:
        parameters["playlist"] = playlist_id
    embed_url = f"https://geo.dailymotion.com/player/{player_id}.html?{urlencode(parameters)}"
    # Preserve the Player ID in the saved URL so editing and restarts do not lose it.
    return MediaLink(embed_url, "dailymotion_playlist" if playlist_id else "dailymotion", video_id or playlist_id, "Dailymotion", embed_url, bool(playlist_id))
