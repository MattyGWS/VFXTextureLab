# Testing VFX Texture Lab 0.46.2.2

## Perspective Transform direction

1. Connect a recognisable photograph to Perspective Transform.
2. Keep Outside set to Transparent or Clamp.
3. Drag both top destination corners inward in the 2D Preview.
4. Confirm the top of the photograph becomes narrower and smaller, rather than expanding toward the viewer.
5. Drag one corner independently and confirm the image follows that corner directly.
6. Confirm the corner gizmo is visible over the Perspective Transform result without enabling an Edit source toggle.
7. Test at Tile 3×3 and confirm the gizmo remains attached to the centre tile.

## Transform 2D

1. Connect a non-square or easily recognisable shape to Transform 2D.
2. Adjust Uniform Scale and confirm both axes resize together.
3. Adjust Scale X only and confirm horizontal stretching/squashing without vertical change.
4. Adjust Scale Y only and confirm vertical stretching/squashing without horizontal change.
5. In the 2D Preview, drag:
   - a corner for uniform scale;
   - the left/right side handles for Scale X;
   - the top/bottom side handles for Scale Y;
   - the centre/interior for position;
   - the external circle for rotation.
6. Rotate first, then use a side handle and confirm it still changes the transform's local axis rather than the screen axis.
7. Undo each complete drag and confirm one drag creates one undo step.

## Compatibility

1. Open a graph authored in 0.46.2.1 or earlier containing Transform 2D.
2. Confirm its existing Scale value produces the same appearance.
3. Confirm Scale X and Scale Y start at 1.0.
4. Confirm Crop still offers Edit crop source and that its source-space bounds remain usable.
