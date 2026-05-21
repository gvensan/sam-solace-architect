"""HTTP routes for the WebUI entrypoint.

Wired into the SAM HTTP-SSE runtime by the plugin's lifecycle.py.

Surfaces (v2spec §6.1 + §6.2):
- Conversational chat: SSE-based (handled by SAM runtime + agent A2A)
- Dashboard JSON APIs: project list + 6 dashboard views
- Intake form: HTML serving + submit + YAML upload + Markdown download
- Audience-pack reports: hosted HTML + PDF + zip
- REST programmatic surface: parity with WebUI APIs
"""

from .api import API_ROUTES

__all__ = ["API_ROUTES"]
