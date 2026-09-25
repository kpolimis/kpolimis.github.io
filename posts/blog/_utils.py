"""Shared footy helpers for World Cup blog posts.

Import from any post under posts/blog/ with:
    import sys, os
    sys.path.insert(0, os.path.join(os.getcwd(), ".."))
    from _utils import _colour, _logo, _bar_colour, _LIGHTEN_BARS
"""
from __future__ import annotations

from functools import lru_cache

import footy

# Liverpool, Fulham, Nottm Forest — all-red badges that collapse under protanopia
_LIGHTEN_BARS: set[str] = {"#c8102e", "#cc0000", "#dd0000"}


@lru_cache(maxsize=None)
def _colour(name: str) -> str:
    """Return the official hex brand colour for a club, or grey if unknown."""
    try:
        return footy.colour(footy.normalise(name))
    except KeyError:
        return "#AAAAAA"


@lru_cache(maxsize=None)
def _logo(name: str) -> str:
    """Return the logo URL for a club, or empty string if unknown."""
    try:
        return footy.logo(footy.normalise(name)) or ""
    except KeyError:
        return ""


def _bar_colour(name: str) -> str:
    """Lighten bars where the badge is all-red and blends with a dark-red background."""
    hex_c = _colour(name)
    if hex_c.lower() in _LIGHTEN_BARS:
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        f = 0.70
        return f"#{int(r + f*(255-r)):02x}{int(g + f*(255-g)):02x}{int(b + f*(255-b)):02x}"
    return hex_c
