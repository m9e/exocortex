"""Entry point: python -m exocortex"""

import uvicorn

from exocortex.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8900)
