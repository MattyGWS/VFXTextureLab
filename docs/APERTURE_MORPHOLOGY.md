# Aperture and Mask Morphology

Version 0.25.0 separates two related but distinct workflows.

## Expand / Shrink

Expand / Shrink is a binary-mask morphology tool. The grayscale input is thresholded, then its silhouette is expanded, contracted, opened, or closed by a pixel distance.

- **Expand** grows white mask regions.
- **Shrink** contracts white mask regions.
- **Open** removes narrow protrusions and isolated details by shrinking then expanding.
- **Close** fills narrow gaps and joins nearby regions by expanding then shrinking.
- **Softness** controls the antialiased transition at the new boundary.
- **Boundary** can wrap seamlessly or clamp at the document edge.

The complete distance analysis and output profile run through WGSL up to 2048 pixels per axis. Larger images retain the memory-safe distance fallback used by Distance and Bevel.

## Outline

Outline extracts a controllable band around the thresholded mask boundary.

- **Inner** keeps the band inside white regions.
- **Outer** keeps the band outside white regions.
- **Centered** straddles both sides of the boundary.
- Width, edge offset, and softness are measured in pixels.

Outline shares the same seamless GPU distance-field pass as Distance, Bevel, and Expand / Shrink.

## Aperture

Aperture is grayscale morphology rather than binary-mask morphology. It reshapes the height values themselves using iterative maximum or minimum filtering.

- **Dilation** propagates nearby high values outward, broadening ridges, peaks, terraces, and raised details.
- **Erosion** propagates nearby low values inward, compacting or cutting into those features.

Available aperture shapes:

- Disk
- Polygon
- Asterisk
- Line
- Corner

Polygon and Asterisk expose a vertex count. Line, Polygon, Asterisk, and Corner expose the shared direction dial. Corner also exposes its opening angle.

The operation is fully GPU iterative and remains seamless by default. Strength blends the reshaped heightfield against the original input.

## Blur GPU completion

Version 0.25.0 also replaces the temporary CPU-compatible execution paths for Directional Blur, Radial Blur, Non-uniform Blur Grayscale, and Slope Blur Grayscale with dedicated WGSL kernels. These nodes now remain GPU-resident in ordinary procedural graphs.
## 0.25.1 footprint correction

Disk now uses a genuinely filled circular structuring element, and Polygon uses a filled regular-polygon element calculated from its vertex count and direction. They are processed in bounded GPU chunks, so increasing Polygon Vertices changes the actual dilation / erosion silhouette instead of every filled shape collapsing into the same square neighbourhood.

Directional Blur also follows the application's shared positive-angle convention from 0.25.1 onward.


## 0.26.0 additional blur tools

This release adds **Anisotropic Blur** and **Zoom Blur** to complement the existing Directional, Radial, Non-uniform, and Slope Blur nodes. Anisotropic Blur gives an oriented elliptical blur useful for streaks, brushed surfaces and motion-like smoothing, while Zoom Blur provides radial in/out streaking from a centre point.
