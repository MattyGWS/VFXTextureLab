# Testing 0.48.1 — Geometry Preview Polish

Use an existing 0.48.0 Geometry test graph or create Geometry Plane connected to Geometry Output and optionally to Material.

## 1. Automatic shaded wireframe

1. Leave **3D Preview Settings → Mesh → Wireframe** at **Auto**.
2. Focus Geometry Plane. Confirm the plane remains solid and shaded, with triangle edges overlaid.
3. Increase and decrease Subdivisions X/Y. Confirm the topology updates immediately and lines do not flicker against the faces.
4. Test Horizontal XZ, Vertical XY and Vertical YZ orientations.
5. Add Height to a Material connected to the plane and adjust viewport displacement. In Always mode, confirm the wireframe follows the displaced surface.

## 2. Auto / Always / Off precedence

1. In Auto, focus Geometry Plane: wireframe must be visible.
2. In Auto, focus Material with Geometry connected: the material should be shaded without wireframe.
3. In Auto, focus an ordinary texture node: the selected standard preview mesh should have no wireframe.
4. Select Always: wireframe should appear on standard meshes, imported glTF/GLB meshes and Material geometry overrides.
5. Select Off: no wireframe should appear, including while Geometry Plane is focused.
6. Save and reopen the graph and confirm the chosen mode is preserved.

## 3. Geometry Plane error regression

1. Set Rendering Backend to CPU, Auto and GPU in turn where available.
2. Focus Geometry Plane and edit Width, Height, subdivisions and orientation repeatedly.
3. Confirm the node does not show an error icon or the message “WGSL package node … has no CPU reference implementation.”
4. Switch rapidly between an image node and Geometry Plane while an image preview is evaluating. Confirm a late image result does not add an error badge to Geometry Plane.
5. Focus a disconnected Geometry Output. It should report its genuine missing-input error; reconnect it and confirm the error clears.

## 4. Regression sweep

- Confirm Material geometry override, standard preview-mesh restoration and OBJ export remain unchanged.
- Test 4× MSAA and Off with Auto and Always wireframe.
- Test opaque, cutout, alpha-blended and additive Material modes with Always wireframe.
- Open a pre-0.48 graph and confirm it loads with Wireframe Auto and no visual changes until a Geometry node is focused.
