# Testing 0.48.2.1 — Wireframe Depth Correction

## Primary regression

1. Create a **Geometry Cylinder** with enough radial, height and cap segments to make the wireframe easy to inspect.
2. Focus the node so shaded + wireframe inspection is active.
3. Orbit until the far interior/back-side topology is directly behind the front wall.
4. Zoom progressively farther away.
5. Confirm hidden lines never become visible through the front surface.

Repeat the same check with **Geometry Box** and **Geometry Plane**, including displaced Material previews when Wireframe is set to **Always**.

## General checks

- Visible topology should remain readable without obvious flicker.
- **Auto / Always / Off** should behave exactly as before.
- Geometry generation, Material overrides and OBJ export should remain unchanged.
