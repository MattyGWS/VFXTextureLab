# Surface Analysis

Version 0.46.0 introduces a dedicated **Filters/Surface Analysis** family for turning authored height and normal information into material masks.

## Height Curvature

`terrain.curvature` keeps its existing implementation and graph identity, but is displayed as **Height Curvature** so it is no longer confused with normal-map curvature.

It accepts a grayscale Height input and offers:

- **Signed** — flat areas are exactly 0.5; convex and concave changes move to opposite sides of neutral grey.
- **Convex** — a black-background ridge mask.
- **Concave** — a black-background valley mask.
- **Absolute** — unsigned curvature magnitude.

Signed is suitable for Overlay-style colour work. The three mask modes are intended for selection and blending rather than neutral Overlay use.

## Curvature

**Curvature** accepts a tangent-space Normal input. It calculates the divergence of the decoded X/Y normal components and produces a sharp signed result:

- 0.5 = flat
- above 0.5 = convex
- below 0.5 = concave

**Intensity** ranges from 0 to 10. **Normal Format** switches between OpenGL (+Y) and DirectX (-Y).

## Curvature Sobel

**Curvature Sobel** applies horizontal and vertical 3×3 Sobel derivatives to the decoded normal field. It creates broader, harder edge bands than the ordinary Curvature node and is particularly useful for stylised material highlights, painted edge accents and cavity darkening.

Intensity uses a focused 0–1 range. Flat normal maps return exact 0.5, so a full-opacity Overlay blend is mathematically neutral away from detected curvature.

## Curvature Smooth

**Curvature Smooth** combines normal changes at three resolution-aware radii. It has three output sockets:

- **Curvature** — signed, neutral-grey curvature
- **Convexity** — black-background convex mask
- **Concavity** — black-background concave mask

The node intentionally has only the input normal convention as an artist parameter. The three-scale weighting is fixed so graph assets and presets remain predictable across resolutions.

## Ambient Occlusion (HBAO)

**Ambient Occlusion (HBAO)** accepts a Height input and produces white for unoccluded regions and darker values where nearby height blocks the hemisphere.

The implementation is height-space horizon AO rather than ray tracing. For each pixel it:

1. Estimates the local tangent plane from the height gradient.
2. Distributes samples over equal-area concentric rings with 4, 8 or 16 azimuth samples per ring.
3. Rotates successive rings by the golden angle so no single set of radial rays is visibly repeated around every feature.
4. Bilinearly samples the Height input and measures only height rising above the tangent plane, preventing a simple planar slope from self-occluding.
5. Converts each relative elevation to a bounded angular contribution and integrates the weighted sample disc into AO transmittance.
6. Reconstructs that sparse estimate with a two-pass joint bilateral filter keyed to the original Height map, smoothing sample footprints while keeping dark lower-surface AO off raised tops.

Parameters:

- **Height Depth** — vertical height scale.
- **Radius** — maximum horizon-search range relative to the texture.
- **Quality** — 4, 8 or 16 azimuth samples per ring; higher settings also use more radial rings.
- **Occlusion Strength** — final occlusion multiplier.
- **Boundary** — Seamless / Wrap for tileable materials or Clamp for non-tiling images.
- **Invert** — reverses the final mask.

During an interactive parameter drag, HBAO temporarily uses four directions and three radial rings. Once interaction settles, the authored quality returns automatically. The graph cache and normal GPU scheduling rules remain unchanged.

Version 0.46.0.1 also compresses Height Depth into a more useful height-space scale. The control continues to increase occlusion throughout its full 0–1 range instead of reaching a nearly saturated horizon response around the middle of the slider.
Version 0.46.0.2 replaces the centred tangent derivative with a slope-limited minmod estimate. This keeps genuine smooth ramps slope-compensated but rejects derivatives that cross an abrupt height discontinuity, removing the false black contour around crisp binary shapes. The reconstruction width follows Radius and resolution and is bounded during interactive editing; all passes remain GPU-resident.


## Ambient Occlusion (RTAO)

RTAO is the accurate ray-marched companion to HBAO. It traces distributed hemisphere rays through the height field, supports 4–64 samples, several ray distributions, maximum travel distance and spread angle, then applies height-aware denoising. Use HBAO for fast iteration and RTAO for higher-quality settled/final evaluation. See [RTAO.md](RTAO.md).
