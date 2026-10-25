"""Bind address for Render.

The Procfile starts `gunicorn app:app`. Gunicorn reads this file and listens
on the PORT Render assigns, on every interface.
"""

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "5000")
workers = 1
timeout = 120
