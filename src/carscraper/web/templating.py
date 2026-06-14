"""Shared Jinja2 environment for server-rendered pages.

Centralizing the `Jinja2Templates` instance here keeps template configuration
(directory, autoescape, etc.) in one place so routers under `web/` (and any
future ones) share the same setup.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
