# Photogrammetry and Scan Preparation

Version 0.46.2 introduced a coherent preparation path for photographs, scanned surfaces, sprite atlases and multi-channel scanned materials. Version 0.46.2.1 replaced the first Make It Tile reconstruction with warped photographic cut masks and added direct manipulation in the 2D Preview. Version 0.46.2.2 corrects Perspective Transform to destination-space editing and adds independent X/Y stretching to Transform 2D.

A typical image workflow is:

```text
Image Input
→ Perspective Transform / Crop
→ Lighting Equalisation
→ Clone Patch
→ Make It Tile Photo
→ Highpass, material generation or export
```

For an already assembled PBR material, Material Crop and Material Make It Tile keep authored channels aligned instead of requiring parallel copies of the same transform nodes.

## Perspective Transform

**Category:** Photogrammetry  
**Input/Output:** Preserves Greyscale, Colour or Vector

Perspective Transform maps the complete source image into an authored destination quadrilateral using a projective homography. It is intended for walls, floors, signs, fabric samples and other photographed surfaces that need projective correction or deformation.

Controls:

- **Top Left / Top Right / Bottom Right / Bottom Left X and Y** — normalised destination positions of the original image corners.
- **Filtering** — Nearest or Bilinear.
- **Outside** — Transparent leaves pixels outside the destination quadrilateral empty; Clamp extends the nearest source border into that area.

Corner coordinates can be typed outside the ordinary `0–1` slider range for unusual framing. Bilinear vector/normal results are renormalised. The four handles are always drawn over the processed Perspective Transform result. Dragging the top pair inward narrows the top of the image exactly as the destination outline indicates.

## Lighting Equalisation

**Category:** Photogrammetry  
**Input/Output:** Preserves Greyscale or Colour; Vector passes through

Lighting Equalisation estimates a broad low-frequency illumination field and divides it out of the photograph. It is useful for reducing directional light, vignetting and broad colour cast before extracting material detail.

Controls:

- **Lighting Radius** — size of the broad illumination estimate in resolution-independent reference pixels.
- **Strength** — interpolation between the original and fully equalised result.
- **Target Luminance** — intended average level after correction.
- **Colour Handling**
  - **Luminance** applies one factor to RGB and better preserves hue.
  - **RGB Channels** corrects broad colour cast independently per channel.
- **Boundary** — Clamp for ordinary photographs or Seamless / Wrap for an already tileable source.

Colour correction is calculated in display-sRGB and returned to the graph's linear-light colour space. Greyscale remains numeric. Normal/vector inputs are deliberately left unchanged because lighting equalisation is not meaningful for encoded directions.

## Clone Patch

**Category:** Photogrammetry  
**Inputs:** Image, optional Greyscale Mask  
**Output:** Preserves input type

Clone Patch copies a circular region from one part of the image to another. It can remove stones, leaves, labels, specular spots, capture equipment or any uniquely recognisable feature that would repeat badly in a tiled texture.

Controls:

- **Source X/Y** — centre of the sampled patch.
- **Target X/Y** — centre at which the patch is placed.
- **Radius** — patch size relative to the shorter image dimension.
- **Feather** — soft transition width.
- **Opacity** — overall patch contribution.
- **Scale / Rotation** — transform the copied source to avoid obvious repetition.
- **Source Boundary** — Clamp or Seamless / Wrap.
- **Mask input** — further restricts destination coverage.

The 2D Preview displays a cross at the source, a target circle and a radius handle. Dragging any of them updates the corresponding parameters interactively while the complete drag remains one undo operation.

## Make It Tile Photo

**Category:** Photogrammetry  
**Input/Output:** Preserves Greyscale, Colour or Vector

Make It Tile Photo is different from the ordinary Tile Transform node. It repairs a source whose opposite edges do not match.

The original photograph remains centred and unchanged through the interior. Near an enabled border, the node reveals a half-period wrapped copy of the source through a detailed transition mask. Horizontal and vertical copies are combined with a diagonal copy at the corners, so opposite output borders sample neighbouring regions of the same centred photograph and join continuously when tiled.

The transition is a cut mask rather than a blurred cross through the image. Its edge is deterministically warped by several periodic detail frequencies, which breaks up visibly straight replacement lines while remaining stable across renders and animation frames.

Controls are independent for horizontal and vertical repair:

- **Mask Size H / V** — how far the wrapped replacement reaches inward from that pair of borders.
- **Mask Precision H / V** — sharpness of the authored cut. Low values produce a broad feather; high values retain a much tighter detailed edge.
- **Mask Warping H / V** — amount of irregular multi-frequency distortion applied to the cut boundary. Zero creates a straight transition for diagnosis.
- **Repair Horizontal / Vertical Tiling** — enable either axis independently.

Use the 2D Preview's **Tile 3×3** mode while adjusting the node. The central portion of the source should remain recognisably identical; only border regions are replaced. Strong unique features near a border may still benefit from Clone Patch before tiling.

## Atlas Splitter

**Category:** Photogrammetry  
**Inputs:** Image, optional Greyscale Mask  
**Output:** Preserves input type

Atlas Splitter detects disconnected shapes; it does not assume equal cells or a square atlas grid. This makes it suitable for scanned leaves, rocks, decals, sprites and other irregular collections.

Controls:

- **Shape Selection** — one-based component index.
- **Selection Order** — Reading Order, Largest First, Left to Right or Top to Bottom.
- **Detection Source** — Alpha or Luminance. An attached Mask overrides this choice.
- **Threshold / Minimum Area** — reject background and tiny fragments.
- **Connectivity** — 4-connected keeps diagonal touches separate; 8-connected joins them.
- **Padding** — include space around the selected bounds.
- **Output Mode** — Crop Auto, Fit (Keep Ratio) or Fill (Stretch).
- **Isolate Component** — clears other detected components inside the selected crop.
- **Filtering** — Nearest or Bilinear.

Connected-component analysis is global and therefore performs one GPU-to-CPU statistics readback when the source is GPU-resident. The selected image is then returned to the normal graph pipeline, and unchanged results remain cached.

## Material Crop

**Category:** Materials  
**Input/Output:** Material

Material Crop applies the same Left, Right, Top and Bottom bounds to every authored channel. Material name, surface mode and other material settings are inherited unchanged. Channels are still lazy: viewing Height does not force Base Colour, Roughness, Normal and the other maps to be evaluated.

## Material Make It Tile

**Category:** Materials  
**Input/Output:** Material

Material Make It Tile applies one shared warped cut-mask repair to every authored material channel. This keeps Base Colour, Height, Roughness, AO, Normal and other maps spatially aligned. Missing channels remain absent, material settings are inherited and normal maps are renormalised after reconstruction.

The Material wrappers use the CPU reference operation after the requested material channel has been resolved for 3D preview/export. They avoid evaluating unrelated channels, but they are not yet a fused all-channel GPU material operation.

## Image-type and resolution behaviour

- Greyscale remains numeric and colour stays in the graph's linear-light representation except where perceptual colour correction is explicitly required.
- Bilinear sampling of vector/normal data is followed by normalisation.
- Rectangle dimensions are respected; the operations do not assume a square document.
- Lighting Equalisation uses the shared resolution-independent blur conventions. Make It Tile uses resolution-independent normalised cut-mask sizes and does not blur the source interior.

## Interactive 2D Preview gizmos

Version 0.46.2.1 adds one shared direct-manipulation system rather than isolated custom editors for each node. Gizmo changes follow the same ParameterSpec clamping, interactive draft scheduling and final-quality release render as ordinary sliders. A complete mouse drag produces one undo entry.

Current gizmos:

- **Transform 2D** — drag the centre or interior to move, drag a corner to change Uniform Scale, drag the left/right or top/bottom side handles to change Scale X or Scale Y, and drag the external circular handle to rotate. Axis handles work in the transform's local rotated space. Middle-drag remains available for panning when the transform covers the image.
- **Clone Patch** — drag the source cross, target centre or radius handle.
- **Perspective Transform** — drag the four destination corners directly over the processed result. No separate source-edit toggle is required because the handles now describe the output quadrilateral.
- **Crop** — enable **Edit crop source**, then drag the four crop corners over the connected source image. Crop retains this source view because its authored bounds are expanded to the full output and therefore cannot be positioned meaningfully over the processed result itself.
- **Centre-position nodes** — any compatible built-in node exposing `center_x` and `center_y` receives a direct position cross automatically.

When Tile 3×3 is enabled, the gizmo is drawn over the central tile so its coordinates still represent one authored texture period. Wheel zoom and middle-button panning continue to work normally.
