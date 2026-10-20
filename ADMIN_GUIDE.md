# Sharing the free course library

Coursemates can browse `/`, `/courses`, `/resources`, `/study`, and `/ask` without an account or subscription. PDFs, video lessons, playlists, references, and course materials are managed from `/admin`.

## First administrator login

Start the site from the application folder (the repository root):

```powershell
python server.py
```

Open `http://localhost:8000/admin` on the computer running the server. The first-run screen lets you choose and confirm a password of at least 12 characters, then signs you in automatically. The Show passwords checkbox lets you check what you typed. Once configured, the setup form is disabled and this page becomes the normal sign-in form.

Browser setup is limited to localhost so a public visitor cannot claim the administrator account. For a hosted server or to reset a forgotten password, run `python manage_admin.py` in the application folder. Terminal password entry is deliberately invisible, including asterisks: type the password and press Enter, then type it again. The password is stored as a salted PBKDF2 hash, not plaintext. There is no default password and no public signup. Resetting the password revokes previous administrator sessions.

## Add resources

- **Courses:** Add a course code, name, and description. Edit course descriptions and names in the Courses tab.
- **PDFs:** Choose the course and PDF, then select **Upload & publish PDF**. Uploads support files up to 50 MB. The PDF tab lists every uploaded document, including existing ones. PDFs become available immediately in the resource library and course page.
- **Videos and playlists:** Select **Video / playlist (detect automatically)**, enter a title, paste a supported link, choose a course or General resources, and publish. Classmates use **Watch here** or **Watch playlist** to play it inside the site. Editing a resource preserves its provider and playlist details. The library can filter all videos or playlists only.
  - YouTube videos: watch, `youtu.be` share, Shorts, live-video, and embed links.
  - YouTube playlists: `/playlist?list=...`, video links with `list=...`, and playlist embed URLs. Video-plus-playlist links keep their selected video and playlist index. The player's playlist controls select other lessons. YouTube uses the privacy-enhanced player domain without autoplay. No API key is required.
  - Vimeo videos: ordinary, player, channel/group video, and unlisted share links. Unlisted privacy hashes are preserved.
  - Vimeo playlists: showcase and legacy album links, including their embed URLs. The showcase owner's plan and sharing settings must permit embedding.
  - Loom: recording share and embed links.
  - Dailymotion: full `https://geo.dailymotion.com/player/PLAYER_ID.html?video=...` or `?playlist=...` URLs. Dailymotion requires a real Player ID. Configure `ARCHIVE_DAILYMOTION_PLAYER_ID` to accept ordinary Dailymotion and `dai.ly` links, or paste a player URL containing its ID. There is no invented default player ID.
  - Direct video files: complete HTTPS URLs ending in `.mp4`, `.webm`, `.ogv`, `.ogg`, or `.m4v`. Signed query strings are retained. Browser codec support and the host's sharing settings determine playback. Streaming manifests such as `.m3u8` are not supported by this player.

  Creators can restrict embedding, regions, or access; every watch page includes an original-source link. Unsupported video platforms can still be saved as **Useful links**. Paste URLs rather than arbitrary iframe HTML. The application never fetches these external URLs on the server.
- **Useful links:** Select Useful website / reference and publish a complete HTTP or HTTPS URL. These open in a separate tab.
- **Study materials:** Choose an indexed PDF and generate shared flashcards, a summary, or glossary. Flashcards appear in `/study`; summaries and glossary entries appear on the course page. A resource link does not automatically ingest video audio, transcripts, or website text into AI search. Ask AI uses the indexed PDFs.

Use **Edit** for video/link details or **Delete** to remove them. Removing a PDF unpublishes it and removes its search index; its stored original is retained on the server. A course with PDFs, videos, or links cannot be deleted until those resources are removed.

## PDF formatting

The reader displays rendered original PDF pages, preserving fonts, diagrams, equations, columns, tables, colors, and page proportions. Fit width, fit page, zoom, page navigation, direct page links, and downloads are available. **Original PDF view** opens the browser's embedded PDF reader, with selectable text and printing where supported. **Text version of this page** provides indexed text separately, without replacing the original layout.

Scanned PDFs can be published and viewed even when no text is available for AI search. OCR requires the optional OCR dependencies and Tesseract installed on the server; enable OCR when uploading a scanned document to make its text searchable.

## Student review progress

Students' flashcard review schedules are stored in their own browser. One student's ratings do not change another student's schedule. Clearing browser storage clears that device's progress; progress does not sync between devices.

## Making the library available online

The changes are implemented locally; starting `server.py` alone does not publish a public website. On a hosting service, run the application behind HTTPS and attach persistent storage for the whole `data/` directory (PDF originals, SQLite databases, vector index, and administrator credentials). Back up that directory. Run `manage_admin.py` on the hosted instance before sharing the site. Configure the proxy to pass the public host and HTTPS scheme so login cookies and same-origin checks work correctly.

The default AI provider is `offline`, so a cloud AI key is not required. If you enable a paid AI provider, requests may incur provider charges even though classmates use the website for free. Hosting, bandwidth, OCR installation, and third-party video availability depend on the deployment environment.

## Verification

```powershell
python -m pytest -q
python test_clean_state.py
python check_rendered_js.py
npm run build:css
```

For an interaction smoke test, start the server and run `python browser_smoke.py` with Google Chrome installed. Tests create isolated data and do not overwrite the live administrator password.

Media integration references: [YouTube players and playlists](https://developers.google.com/youtube/player_parameters), [Vimeo showcase embeds](https://developer.vimeo.com/api/oembed/showcases), [Vimeo unlisted privacy hashes](https://help.vimeo.com/hc/en-us/articles/12426470858001-Embedded-player-displays-This-video-does-not-exist-message), [Loom embeds](https://support.atlassian.com/loom/docs/embed-your-video-into-a-webpage/), and [Dailymotion player IDs](https://developers.dailymotion.com/v0/reference/migration-guide-new-embed-endpoint).
