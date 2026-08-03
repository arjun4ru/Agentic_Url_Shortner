"""Agentic SDLC orchestration engine.

See docs/DESIGN.md for the full architecture. This package contains no
third-party dependencies on purpose -- it only orchestrates; the agents it
drives may touch the url_shortener/ product, which does depend on FastAPI.
"""
