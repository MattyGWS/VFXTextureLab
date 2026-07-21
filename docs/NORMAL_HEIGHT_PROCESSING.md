# Normal and Height Processing

Version 0.46.3 established the coherent toolkit for composing, repairing, transforming and reconstructing tangent-space normal maps, plus height-derived bent normals and directional shadows. Version 0.46.5.1 adds Directional Lighting as the local normal-derived lighting-mask counterpart to RT Shadows.

All normal-map nodes operate on decoded unit vectors rather than treating encoded RGB as ordinary colour. The selected **Normal Format** controls whether the encoded green channel follows OpenGL `+Y` or DirectX `-Y`; results are converted back into the same requested convention on output.

## Normal Blend

**Normal Blend** is a maskable crossfade between Background and Foreground normals.

- **Amount** sets the global blend weight.
- An optional **Mask** multiplies Amount per pixel.
- Both inputs are decoded and repaired before blending.
- The blended vector is renormalised before encoding.

This node is useful for ordinary interpolation, fades and artist-authored masks. It is not intended to preserve the full apparent strength of two simultaneously layered normal maps; use Normal Combine for that purpose.

## Normal Combine

**Normal Combine** layers a Detail normal over a Base normal.

- **Reoriented (RNM)** rotates the detail orientation into the base surface frame. It is the recommended default and treats a flat detail normal as an exact identity.
- **Whiteout** adds tangent slopes and multiplies Z. It often creates a stronger, punchier result.
- **UDN** adds tangent slopes while retaining the base Z component. It is inexpensive and familiar, but less orientation-preserving than RNM.
- **Base Strength** and **Detail Strength** scale each map's tangent slope before combination.
- **Amount** and the optional **Mask** blend between the original Base and the combined result.

Every method emits a repaired unit vector.

## Normal Normalize

**Normal Normalize** restores unit length after imported, filtered or mathematically generated normal data. Zero-length or invalid vectors become a flat tangent-space normal `(0, 0, 1)`.

## Normal Invert

**Normal Invert** flips selected decoded axes:

- **Invert X / Red** mirrors the horizontal tangent direction.
- **Invert Y / Green** mirrors the vertical tangent direction.
- **Invert Z / Blue** flips the outward direction and should normally remain disabled unless a specialised workflow requires it.

Changing between OpenGL and DirectX conventions is usually best handled by setting the correct Normal Format. Invert Y remains available for explicit artistic or pipeline repair.

## Normal Vector Rotation

**Normal Vector Rotation** rotates the decoded tangent-space XY direction around the local surface Z axis while leaving the image coordinates completely unchanged.

- **Rotation** supports positive, negative and multi-turn angles and can be animated.
- **Normal Format** selects OpenGL `+Y` or DirectX `-Y` interpretation and output encoding.
- Every output is renormalised; a flat `(0, 0, 1)` normal remains flat at every rotation.

Use this when the texture pattern is already positioned correctly but its apparent tangent-space lighting direction needs to turn. Use **Normal Transform** when the texture itself must also move, scale, tile or rotate.

## Directional Lighting

**Directional Lighting** converts a tangent-space normal map into a grayscale local-lighting mask. It is intentionally separate from RT Shadows: Directional Lighting evaluates only the orientation stored at each texel, while RT Shadows traces across a height field to determine cast occlusion.

- **Light Angle** controls the horizontal direction toward the light.
- **Light Elevation** moves from grazing to overhead illumination.
- **Diffuse Power/Brightness** shape the broad Lambert-style response.
- **Highlight Power/Brightness** add an optional view-facing lobe for stylised highlights and masks.
- **Ambient** lifts dark regions and **Invert** swaps the final mask.
- **Normal Format** supports equivalent OpenGL and DirectX inputs.

The Preview light gizmo edits angle and elevation together. The node remains one GPU compute pass with no readback.

## Normal Transform

**Normal Transform** provides Offset X/Y, Uniform Scale, Scale X, Scale Y, Rotation and Tile.

Unlike an ordinary image transform, rotating the image also rotates the decoded tangent-space XY vector. Bilinear samples are renormalised and non-tiled regions outside the transformed image become a flat normal rather than transparent or black vector data.

The node uses the shared 2D Preview transform gizmo:

- drag the centre or interior to move;
- drag a corner for uniform scale;
- drag a side handle for independent horizontal or vertical stretch;
- drag the external circle to rotate.

One complete drag creates one undo step.

## Normal to Height

**Normal to Height** reconstructs an approximate seamless height field from the slope information stored in a tangent-space normal map.

The solve uses global Frankot-Chellappa/Poisson integration in the frequency domain:

- **Height Intensity** expands or compresses the reconstructed relief around mid-grey.
- **Low Frequency** controls broad forms.
- **High Frequency** controls fine detail.
- **Normalize Output** maps the reconstructed range into `0–1`; when disabled, the signed solution remains centred around `0.5` and is clipped to the graph range.
- **Invert** reverses the result.

A normal map contains local direction, not an absolute height reference. Multiple height fields can produce similar normals, flat offsets are lost, inconsistent painted normals cannot integrate perfectly, and seams in a non-tileable normal map can influence the global solution. The result is therefore a useful reconstruction for masks, AO, displacement preparation and detail recovery—not a guarantee of the original source height.

The FFT solve requires whole-image access. When the upstream normal is GPU-resident, the node performs one deliberate readback, solves on the CPU, uploads the grayscale result and returns to the normal GPU graph path. Unchanged results remain cacheable.

## Bent Normal

**Bent Normal** traces hemisphere visibility through the input Height surface and stores the average unoccluded direction instead of reducing visibility to a single AO value.

Controls mirror the RTAO workflow:

- **Height Scale** sets vertical relief.
- **Samples** controls hemisphere rays per pixel.
- **Distribution** chooses Uniform, Cosine Weighted or Horizon Weighted directions.
- **Maximum Distance** limits blocker reach.
- **Spread Angle** narrows or opens the sampled hemisphere.
- **Denoise** controls the two-pass height-aware reconstruction.
- **Boundary** chooses Seamless/Wrap or Clamp.
- **Normal Format** selects output encoding.

A flat height field outputs a flat normal. Near a blocker, the result bends away from the blocked part of the hemisphere. The ray pass and both denoise passes remain GPU-resident; interactive edits use a reduced draft workload and resolve the authored quality after release.

## RT Shadows

**RT Shadows** generates a directional shadow mask by marching rays from every height pixel toward an area light.

- **Light Angle** is the horizontal direction from the surface toward the light.
- **Light Elevation** raises or lowers the light above the height plane.
- **Height Scale** controls the apparent vertical relief.
- **Maximum Distance** limits shadow reach.
- **Softness** spreads multiple light samples around the authored direction and elevation.
- **Samples** controls area-light sampling from a hard single ray through smoother soft shadows.
- **Bias** prevents immediate self-intersection at the ray origin.
- **Shadow Strength** blends blocked pixels back toward white.
- **Boundary** selects Seamless/Wrap or Clamp.
- **Invert** swaps the lit/shadow convention.

The node output is white for lit regions and black for fully blocked regions. It uses software ray marching in the WebGPU compute backend and does not require hardware ray-tracing support. Parameter drags temporarily cap the sample count and march depth for responsiveness.
