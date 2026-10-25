#!/usr/bin/env python3
"""Start the student viewer.

Render imports the Flask object named app and starts it with Gunicorn.
Running this file directly starts the local server on PORT, or 5000.

    python app.py
"""

import os

from server import app, main

port = int(os.environ.get("PORT", 5000))

__all__ = ["app", "port"]

if __name__ == "__main__":
    os.environ["PORT"] = str(port)
    main()
