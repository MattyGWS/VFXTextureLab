"""Shared high-density geometry preview limits.

This module intentionally has no Qt, renderer, or package-level dependencies.
UI code and the 3D renderer both import these values, so keeping them here
prevents startup import cycles between ``vfx_texture_lab.ui`` and
``vfx_texture_lab.three_d``.
"""

from __future__ import annotations


AUTO_WIREFRAME_TRIANGLE_LIMIT = 250_000
