#!/usr/bin/env python3
"""Shared shields-style badge SVG renderer for the AGILAB badge generators.

Single source of truth for badge geometry and escaping so
``generate_skill_badges`` and ``generate_component_coverage_badges`` cannot
drift. Text is centered with ``text-anchor="middle"`` over each rect, and the
same width estimate drives both the rect width and the centering ``x`` so the
label stays centered regardless of the estimate's accuracy.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

# Per-character advance widths (in px at font-size 11, DejaVu Sans-ish),
# quantized for stability. Narrow glyphs (i, l, punctuation) and wide glyphs
# (m, w, %, uppercase) are approximated so the reserved box tracks the rendered
# run far better than a flat monospace grid, avoiding clipping and excess pad.
_NARROW = set("ijl.,:;'|!")
_WIDE = set("mwMW%@_")
_EXTRA_WIDE = set("—…")


def _char_width(char: str) -> float:
    if char in _NARROW:
        return 3.5
    if char in _EXTRA_WIDE:
        return 11.0
    if char in _WIDE:
        return 9.5
    if char.isupper():
        return 8.0
    return 6.5


def text_width(text: str) -> int:
    """Estimate the rendered pixel width of ``text`` plus horizontal padding."""
    return 10 + round(sum(_char_width(char) for char in text))


def render_badge(label: str, value: str, color: str) -> str:
    """Return a two-segment shields-style badge SVG for ``label``/``value``."""
    label = str(label)
    value = str(value)
    left = text_width(label)
    right = text_width(value)
    total = left + right
    left_mid = left / 2
    right_mid = left + right / 2
    aria = escape(f"{label}: {value}", {'"': "&quot;"})
    label_xml = escape(label)
    value_xml = escape(value)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{aria}">
<linearGradient id="b" x2="0" y2="100%">
  <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
  <stop offset=".1" stop-opacity=".1"/>
  <stop offset=".9" stop-opacity=".3"/>
  <stop offset="1" stop-opacity=".5"/>
</linearGradient>
<mask id="a">
  <rect width="{total}" height="20" rx="3" fill="#fff"/>
</mask>
<g mask="url(#a)">
  <rect width="{left}" height="20" fill="#555"/>
  <rect x="{left}" width="{right}" height="20" fill="{color}"/>
  <rect width="{total}" height="20" fill="url(#b)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
  <text x="{left_mid}" y="15" fill="#010101" fill-opacity=".3">{label_xml}</text>
  <text x="{left_mid}" y="14">{label_xml}</text>
  <text x="{right_mid}" y="15" fill="#010101" fill-opacity=".3">{value_xml}</text>
  <text x="{right_mid}" y="14">{value_xml}</text>
</g>
</svg>
"""
