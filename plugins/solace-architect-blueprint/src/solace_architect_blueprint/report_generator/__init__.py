"""Ported V1 HTML report generator (v2spec §5.5).

Phase 2 vertical slice: minimal renderer producing a self-contained branded HTML
report for the Blueprint pack. Phase 3 ships full templates for all 5 packs,
the ROI calculator JS, and WeasyPrint-driven PDF rendering.
"""

from .render import render as render_pack
from .render import render_audience_pack_html, render_audience_pack_pdf

__all__ = ["render_pack", "render_audience_pack_html", "render_audience_pack_pdf"]
