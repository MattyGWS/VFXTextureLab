# Immediate Essential Filters

Version 0.46.1 adds six foundational nodes intended to support later generator, photogrammetry, normal-processing and transform work.

## Histogram Select

**Category:** Filters  
**Input:** Greyscale Image  
**Output:** Greyscale Image

Histogram Select isolates a band around a chosen value. It differs from the existing histogram nodes:

- **Histogram Range** compresses the complete input range.
- **Histogram Shift** offsets and wraps all values.
- **Histogram Scan** grows or shrinks a thresholded region.
- **Histogram Select** returns a band centred on one value.

Controls:

- **Position** — centre of the selected value band.
- **Range** — full width of the selected band.
- **Contrast** — tightness of the transition at both band edges.

The Inspector uses the shared live input histogram with guides for the centre and both range edges.

## Highpass

**Category:** Filters  
**Input/Output:** Preserves Greyscale or Colour

Highpass removes low-frequency variation and recentres the retained detail around visible 50% grey. Common uses include extracting pores or scratches, reducing broad lighting variation from photographs, and sharpening by blending the result back with Overlay.

Controls:

- **Radius** — resolution-independent frequency-separation radius. Larger values retain progressively broader detail.
- **Boundary** — **Clamp** is appropriate for non-tiling photographs; **Seamless / Wrap** allows already tileable textures to sample across their borders.

Colour sources are converted from the graph's linear-light storage into display-sRGB for the separation and converted back afterward. This makes the displayed midpoint neutral with the corrected colour Overlay mode. Greyscale sources retain raw numeric behaviour.

## Edge Detect

**Category:** Filters  
**Input:** Any image  
**Output:** Greyscale

Edge Detect evaluates a spatial derivative. Greyscale remains numeric, colour uses display-sRGB luminance, and normal/vector inputs use decoded vector differences so chromatically balanced normal edges are not lost.

Controls:

- **Method** — **Scharr** offers improved rotational balance; **Sobel** provides the familiar classic response.
- **Width** — resolution-independent sample distance.
- **Intensity** — output gain.
- **Invert** — returns white non-edges and dark edges.

## FXAA

**Category:** Filters  
**Input/Output:** Preserves Greyscale, Colour or Vector

FXAA is a post-process anti-aliasing filter. It locates high-contrast neighbourhoods, estimates the edge direction from diagonal luminance gradients, searches fractional samples along that edge, and rejects samples that would cross outside the local luminance range.

Controls:

- **Quality** — Low, Medium or High search span.
- **Edge Threshold** — minimum absolute contrast before filtering.
- **Relative Threshold** — contrast threshold relative to the brightest local sample.
- **Subpixel** — final filtering strength.
- **Preserve Alpha** — retains the original alpha channel.

Colour images are filtered perceptually in display-sRGB. Vector/normal images are decoded before filtering and renormalised afterward so the resulting vectors retain unit length.

## Crop

**Category:** Transform  
**Input/Output:** Preserves Greyscale, Colour or Vector

Crop remaps a normalised rectangular source region to the full output canvas.

Controls:

- **Left / Right / Top / Bottom** — normalised source bounds.
- **Filtering** — Nearest or Bilinear.

Bounds may be entered in either order. Crop supports rectangular documents, and normal/vector outputs are renormalised after interpolation.

## Auto Crop

**Category:** Transform  
**Input/Output:** Preserves Greyscale, Colour or Vector

Auto Crop finds the bounding box of content above a threshold and then frames it automatically.

Controls:

- **Mode**
  - **Crop Square** — expands the detected bounds to the smallest enclosing square, shifts that square inside the source when it reaches an edge, and maps it to the output.
  - **Crop Auto** — centres the detected content without changing its pixel scale. This is the fixed-canvas form of an automatic crop and is useful for off-centre sprites and shapes.
  - **Fit (Keep Ratio)** — centres the content and preserves its aspect ratio, leaving empty bars where required.
  - **Fill (Stretch)** — stretches the detected rectangle to the complete output.
- **Use Alpha** — detect from alpha instead of luminance.
- **Threshold** — minimum detected content value.
- **Padding** — extra normalised space around the detected bounds.
- **Filtering** — Auto, Nearest or Bilinear. Auto keeps direct crop modes crisp and uses Bilinear for fit/stretch.

Finding a global bounding box currently requires one GPU-to-CPU statistics readback. The detected bounds are then supplied to a native GPU resampling pass. Normal graph caching means an unchanged upstream result does not repeatedly evaluate merely because the node is viewed elsewhere.
