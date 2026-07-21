# Transform Quality

Version 0.46.4 gives the image-moving nodes one common resampling contract. The goal is not to make every transform node identical; it is to ensure that the same filtering name, boundary name, pixel coordinate and image type always mean the same thing.

## Shared pixel convention

A texel is sampled at its centre. Identity transforms bypass resampling completely, and integer-pixel Offset operations use exact nearest sampling. This prevents a neutral transform from introducing a half-pixel shift or softening an otherwise unchanged texture.

Rotation in Transform 2D, Rotate, Normal Transform and Clone Patch is performed in physical image pixels. On a rectangular document, a 20-pixel radius remains 20 pixels after a 90-degree rotation instead of being stretched by the canvas aspect ratio. The Transform 2D/Normal Transform gizmo uses the same rule.

## Filtering

### Automatic

The recommended general-purpose mode. It uses cubic reconstruction when the transform is enlarging or sampling near one source texel per output texel, then increases the sampling footprint when the source is being reduced. Perspective Transform estimates this footprint locally because different parts of a projective warp can enlarge and shrink at the same time.

### Nearest

Copies the nearest texel exactly. This is appropriate for pixel art, hard IDs, intentionally stepped masks and exact integer-pixel movement.

### Bilinear

Blends the nearest four texels. It is fast and predictable, but repeated transforms can soften detail.

### Bicubic

Uses a Mitchell-Netravali cubic reconstruction kernel. It is sharper and smoother than Bilinear for photographs and moderate scaling while avoiding the aggressive ringing of some sharper cubic kernels.

## Boundaries

- **Transparent** returns zero alpha outside the image. For grayscale data, the outside value is black. For normal/vector data, it is a transparent flat vector.
- **Clamp** extends the nearest border texel.
- **Seamless / Wrap** samples the opposite border periodically.
- **Mirror** reflects the image at each border.

The general transform family shares these four choices. Nodes with a deliberately narrower purpose may expose only the choices that make sense: Safe Transform is always periodic, while Atlas Splitter crops detected content rather than sampling an unbounded transform.

## Typed resampling

### Colour and alpha

Colour is interpolated with premultiplied alpha. Hidden RGB in transparent texels therefore cannot create green, black or bright fringes around a rotated cutout. The result is unpremultiplied after filtering for normal graph storage.

### Grayscale, height and masks

Values are sampled numerically. No colour-space conversion is introduced, and a value of `0.5` remains the numeric midpoint.

### Normal and vector maps

Encoded RGB is decoded to a signed vector before interpolation. The result is renormalised and encoded again. Normal Transform additionally rotates tangent-space XY directions when the image itself rotates.

## Safe Transform

Safe Transform is deliberately separate from Transform 2D.

Transform 2D is a literal general image transform with selectable outside behaviour. Safe Transform is periodic by construction and is intended for procedural textures, noises, grunge and already-seamless photographs.

Its controls are:

- **Tile** — integer repetition count.
- **Offset Mode** — Manual or deterministic Random.
- **Offset X/Y** — snapped to output pixels so authored offsets remain stable and exact.
- **Random Seed** — chooses a deterministic snapped offset.
- **Rotation** — requested angle.
- **Tile Safe Rotation** — maps that request to a nearby integer lattice direction, preserving exact periodicity on opposing borders.
- **Symmetry** — None, X, Y or X + Y periodic reflection.
- **Filtering** — the shared four interpolation choices.
- **Mipmap Mode / Level** — Automatic uses the transform footprint; Manual adds a larger prefilter footprint for deliberate loss of high-frequency detail.

At low Tile values, only a small number of integer lattice directions are available, so a tile-safe rotation may differ visibly from the requested angle. Increasing Tile allows a closer angular approximation. Disabling Tile Safe Rotation honours the exact angle but gives up the integer-lattice guarantee.

## Upgraded nodes

The shared system is used by:

- Transform 2D
- Tile
- Offset
- Rotate
- Scale
- Crop
- Auto Crop
- Perspective Transform
- Clone Patch
- Atlas Splitter output resampling
- Normal Transform
- Material Crop channel processing
- Safe Transform

Perspective Transform calculates a local projective footprint. Auto Crop and Atlas Splitter still require their existing whole-image CPU analysis to find bounds/components, but their final resampling uses the same typed rules.

## Compatibility

The graph format remains version 18. Older Transform 2D and Normal Transform `Tile` values, and older Offset/Rotate/Scale `Wrap` values, are translated into the matching Boundary option when a graph is opened. The former `Auto` filter label is translated to `Automatic`.
