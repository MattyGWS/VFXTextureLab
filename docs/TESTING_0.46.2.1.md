# Testing VFX Texture Lab 0.46.2.1

This revision focuses on the rebuilt photographic seam construction and the first reusable 2D Preview gizmos.

## 1. Make It Tile Photo — real photograph

1. Load a visibly non-tiling photograph with recognisable detail near all four borders.
2. Connect **Make It Tile Photo** and enable **Tile 3×3** in the 2D Preview.
3. Confirm the centre of the photograph has not been shifted or blurred. The original composition should remain centred.
4. Increase **Mask Size H** and confirm only the left/right replacement reaches farther inward. Repeat with **Mask Size V** for top/bottom.
5. Set **Mask Warping H/V** to `0`. The transition should become deliberately straight and easy to identify.
6. Raise warping toward `50–100`. The cut should become irregular and detailed rather than a straight fade.
7. Compare low and high **Mask Precision**. Low values should feather broadly; high values should make a tighter, sharper cut without drawing a hard line.
8. Disable horizontal or vertical repair individually and confirm only that pair of borders changes.
9. Inspect the repeated result at 1:1. There should be no blurred cross through the centre and no visible discontinuity at the outer tile boundaries.

A strong unique object directly on a border may still need **Clone Patch** first; this is expected rather than a seam failure.

## 2. Material Make It Tile

1. Assemble a Material with at least Base Colour, Height and Normal.
2. Pass it through **Material Make It Tile** using the same mask settings as the image test.
3. Inspect each channel through Material Channels and in Tile 3×3 mode.
4. Confirm all channel transitions occupy the same locations and the normal map remains valid rather than becoming dim/unnormalised.
5. Change only one viewed/exported channel and inspect Evaluation Inspector; unrelated missing or unrequested channels should not be evaluated eagerly.

## 3. Transform 2D gizmo

1. Select or preview a **Transform 2D** node.
2. Drag the centre cross or inside the box; Offset X/Y should update.
3. Drag a corner; Scale should update uniformly.
4. Drag the external circular handle; Angle should update continuously.
5. Undo once after a long drag. The entire drag should revert in one operation, not one undo per mouse-move event.
6. Enable Tile 3×3 and confirm the handles remain on the central tile.
7. Use middle-drag to pan while the transform box covers most of the image.

## 4. Clone Patch gizmo

1. Select **Clone Patch** with a photograph connected.
2. Drag the source cross to a clean region.
3. Drag the target centre over an unwanted object.
4. Drag the radius handle on the target circle.
5. Confirm Source X/Y, Target X/Y and Radius remain synchronised with the visual handles and preview interactively.

## 5. Perspective Transform and Crop source editing

1. Select **Perspective Transform** and click **Edit source** in the 2D Preview toolbar.
2. Confirm the preview changes to the connected unprocessed source, then drag all four corners around a photographed rectangular surface.
3. Disable **Edit source** and inspect the rectified output.
4. Repeat with **Crop**. Drag the four source-space crop corners, then disable Edit source to inspect the remapped output.
5. Confirm source editing and output inspection can be toggled repeatedly without losing the authored coordinates.

## 6. Generic centre handles

1. Preview a compatible node with **Center X** and **Center Y** parameters, such as a radial/zoom-style filter.
2. Drag the centre cross in the 2D Preview.
3. Confirm both parameters update and the result uses interactive draft evaluation during the drag followed by a settled final render.

## 7. Compatibility and regression

1. Open a graph saved in the initial 0.46.2 release with Make It Tile Photo or Material Make It Tile.
2. Confirm it loads without errors and the legacy seam width/detail intent appears in the new Size/Precision controls.
3. Save and reopen it; obsolete Seam Width, Seam Blur and Detail Preservation controls should not return.
4. Sanity-check Lighting Equalisation, Atlas Splitter, Perspective Transform, Clone Patch and the six 0.46.1 Immediate Essentials nodes.
