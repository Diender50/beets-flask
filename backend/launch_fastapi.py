"""Launch the FastAPI server on port 5002 (parallel to Quart on 5001)."""

import uvicorn

from beets_flask.server_v2.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "launch_fastapi:app",
        host="0.0.0.0",
        port=5002,
        reload=True,
        reload_dirs=["beets_flask"],
    )
