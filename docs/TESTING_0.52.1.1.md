# Testing VFX Texture Lab 0.52.1.1

This is a source-only correction. Do not rerun setup after replacing 0.52.1.

## Textureless UV preview

1. Connect geometry to **Geometry UV Unwrap** and complete an unwrap.
2. Leave **Preview Texture** disconnected.
3. Confirm the 2D Preview continues to show its checkerboard beneath the UV islands.
4. Confirm the same unwrapped mesh now displays a neutral checkerboard in the 3D Preview rather than plain white shading.
5. Connect an image to **Preview Texture** and confirm it replaces the checker in both 2D and 3D without making the node Out of Date.
6. Disconnect the image and confirm the checker returns immediately without requiring Re-Unwrap.
7. Save and reopen the graph, then confirm the stored unwrap restores with the checker fallback.

## Regression checks

- Geometry Remesh and Geometry Delete Small Parts
- Automatic Charts and projection unwrap modes
- Manual-action persistence, cancellation and stale-state handling
- Material preview and ordinary geometry inspection
