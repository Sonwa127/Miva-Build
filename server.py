"""Server entry point for StitchSmart Course Study Assistant."""
import os

import uvicorn

if __name__ == "__main__":
    print("Starting StitchSmart Course Study Assistant...")
    print("Web UI available at: http://localhost:8000")
    print("Interactive API Docs: http://localhost:8000/docs")
    # File watching is useful during development but creates extra processes and
    # can exhaust resources on smaller Windows machines. Opt in when needed.
    reload_enabled = os.getenv("ARCHIVE_RELOAD", "0") == "1"
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=reload_enabled)
