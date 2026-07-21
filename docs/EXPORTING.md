# Output and export workflow

VFX Texture Lab 0.45.1 keeps material authoring separate from reusable export templates and production profile sets:

```text
Texture branches → Material → one or more Texture Set Output nodes
```

The purple **Material** connection is a lightweight structural bundle. It carries references to the connected PBR branches and material settings; it does not merge or duplicate the images.

## Material

Material defines the maps used by the 3D Preview and by Texture Set Output:

- Base Colour
- Emissive
- Normal
- Height
- Ambient Occlusion
- Metallic
- Roughness
- Specular Level
- Opacity

Double-click Material to make it the active preview target. The connected Base Colour appears in the 2D Preview while the complete material appears in 3D.

One Material can feed several Texture Set Outputs, allowing separate Unreal, Unity and unpacked-map export configurations without wiring every texture more than once.

## Texture Set Output

Texture Set Output has one typed **Material** input and remains a terminal export endpoint. The Material supplies semantic channels; the selected **Export template** decides which files are written and what each file channel contains.

Built-in templates are read-only starting points:

- **Generic PBR Separate** — BaseColor, Normal, Emissive, Opacity, Height, AO, Roughness, Metallic and Specular maps.
- **Unreal ORM** — AO, Roughness and Metallic packed into R/G/B.
- **Unity HDRP Mask Map** — Metallic R, AO G, Constant 1 B and Smoothness (`1 - Roughness`) A.
- **Godot ORM** — AO, Roughness and Metallic packed into R/G/B.
- **VFX RGBA Masks** — Opacity R, Emissive luminance G, Height B and AO A.

All built-ins use the same export-template backend as authored layouts. This removes preset-specific export code and keeps future engine, terrain and studio templates on one path.

### Export Template Editor

Expand **Template Editor** in the Texture Set Output Inspector and choose **Customise Template…**. Saving creates a graph-local **Custom Template** while leaving built-ins unchanged.

A template can contain any number of output files. Each file controls:

- Display label and `{map}` token value.
- Optional per-file name pattern; otherwise it inherits the node's File name pattern.
- PNG, TGA, Raw R16, Texture-set setting or Height setting format.
- Colour setting, Scalar setting, explicit 8-bit or explicit 16-bit depth.
- Grayscale, RGB or RGBA layout.
- sRGB or Linear handling.
- Optional export even when every semantic source is absent.

R, G, B and A assignments can use:

- Base Colour, Emissive or Normal components and luminance.
- Height, AO, Metallic, Roughness, Specular Level or Opacity.
- Constant 0 or Constant 1.
- Per-channel inversion.

The special **Normal · Green / Y convention** source follows the output node's OpenGL (+Y) or DirectX (-Y) setting automatically. Missing assigned channels use the semantic Material defaults whenever another assigned source keeps the file active—for example AO 1, Roughness 0.5 and Metallic 0 in a partially connected ORM map.

Custom templates are stored inside `.vfxgraph` data. They therefore survive Save/Load, undo/redo, Self-Contained Graph export and `.vfxpackage` creation without a separate sidecar file.

Base Colour and Emissive are normally transfer-encoded and tagged as sRGB. Normal, height, scalar maps and packed masks preserve numeric values and intentionally carry no PNG colour/gamma profile. The editor permits deliberate alternatives but preflight warns about suspicious choices such as scalar-only sRGB outputs or 8-bit Height.

## Quick Export

Select either a Texture Set Output or Single Image Output and open its **Quick Export** parameter group.

The first press of **Quick Export** opens Export Outputs with only that endpoint listed. Choose the destination, existing-file policy and whether the folder should open after completion. After a successful export, those choices are stored in that output node and saved with the graph.

Later presses export that texture or texture set immediately with the stored destination and complete profile-set snapshot. **Configure Export…** reopens the full output/target setup. The Quick Export group shows the remembered profile name, and its **Open folder when complete** checkbox can still be changed directly in the Inspector.

## Single Image Output

Use Single Image Output for one texture, including masks, standalone normal maps, custom channel packs and Flipbook Generator atlases.

The semantic presets are:

- **Auto from data type** — Colour exports as 8-bit sRGB RGBA PNG, Vector / Normal as 8-bit linear RGB PNG, and Greyscale as 16-bit linear PNG.
- **Colour / sRGB** — display-colour texture.
- **Linear Data** — scalar or packed data without display transfer conversion and without PNG colour/gamma metadata.
- **Normal Map (OpenGL +Y)** — linear normal output without Green/Y inversion.
- **Normal Map (DirectX -Y)** — linear normal output with Green/Y inversion during export.
- **Custom** — exposes format, depth, channels, grayscale source, encoding, inversion and Green/Y controls.

File names support `{output}`, `{graph}`, `{version}`, `{profile}`, `{target}`, `{width}` and `{height}`. Texture-set files additionally support `{set}` and `{map}`. Resolution can follow the document, use a square preset from 256 through 8192, or use custom width and height.

For a custom packed material texture, use **Channel Pack** followed by Single Image Output.


### Colour encoding and document settings

Output encoding is semantic and belongs to the output endpoint. The document's graph settings do not force normal maps, masks or scalar data through sRGB.

- Colour/sRGB converts linear graph colour to sRGB code values and embeds the PNG `sRGB` chunk.
- Linear Data and normal presets leave numeric channels unchanged and write no `sRGB` or `gAMA` chunk.
- TGA has no equivalent colour-profile chunk; colour outputs are still numerically sRGB encoded while data outputs remain numeric/linear.
- Raw R16 always contains little-endian unsigned 16-bit numeric height values.

This makes the 2D Preview and ordinary external image viewers agree visually for data maps while preserving exact channel values for engines and downstream tools.

## Flipbook Generator

Flipbook Generator samples an animated branch and produces an atlas as an ordinary image output. Connect it to Single Image Output to export the atlas with the same naming, format and collision workflow as every other image.

## Batch export

### Export profile sets and targets

The **Export Profile Set** section sits between Graph Outputs and Planned Files. A profile set is a graph-local list of production targets that should be published together. The default profile contains one **Current Output** target and therefore behaves exactly like the 0.45.0 export workflow.

A target can use the Texture Set Output node's current template or select another built-in template. It can also override only the settings that need to differ for that destination:

- Relative output subfolder.
- Resolution.
- OpenGL or DirectX normal convention.
- PNG or TGA texture format.
- Colour and scalar bit depths.
- PNG 16-bit or Raw R16 Height.

For example, one profile can contain **Unreal Production**, **Source Archive** and **Mobile** targets. Every selected Texture Set Output is passed through all enabled targets in one export request, while selected Single Image Outputs are written once using their own node settings. Target subfolders may use `{graph}`, `{version}`, `{profile}`, `{target}`, `{output}` and `{set}` and are always resolved beneath the chosen output folder.

Profiles and targets can be created, duplicated, renamed, enabled, edited or removed in Export Outputs. They are stored inside the graph, so they travel through Self-Contained Graph and `.vfxpackage` export automatically. Cancelling the dialogue discards profile edits; accepting it saves them with the graph.

The evaluator reuses each source/output/resolution result across the whole request. Publishing Unreal and Godot at the same resolution therefore evaluates Base Colour, Normal, Height and masks once and only performs the different channel packing and file writing afterward. A target at another resolution receives the one additional evaluation that resolution requires.


Choose **File → Export Outputs…** or press `Ctrl+E`.

The window lists every explicit output endpoint and previews the files each one plans to create. `Include in batch export` controls its default checked state; a disabled endpoint can still be selected manually for a one-off export.

The **Planned Files** preflight updates with the selected endpoints and shows the resolved filename, effective format and bit depth, channel layout, colour handling and resolution before graph evaluation starts. Duplicate target names and non-blocking template warnings appear inline.

The **Open output folder when complete** checkbox remembers its previous state.

Existing-file policies are:

- **Replace existing** — the default. Re-exporting the same output node updates the same files in place.
- **Add numeric suffix** — deliberately preserves existing files by finding the next `_2`, `_3`, and later name.
- **Skip existing** — leaves existing destinations untouched.

If two selected output nodes genuinely plan the same filename in one batch, VFX Texture Lab warns before writing and appends stable node-specific tags only to those conflicting files. The same batch therefore overwrites the same safe paths on its next run instead of growing another numeric suffix each time. Rename the output nodes or their filename templates to remove the warning and keep cleaner filenames.

Right-click a Single Image Output or Texture Set Output for **Export This Output…**. Box-select several output nodes and right-click one of them for **Export Selected Outputs…**.

## Focused test checklist

1. Open a new graph and confirm the layout reads left-to-right as generation → Material → Texture Set Output.
2. Double-click Material and confirm Base Colour appears in 2D and the full material appears in 3D.
3. Double-click the connected Texture Set Output and confirm it shows the same Base Colour and material.
4. Double-click the already-active Material again and confirm it refreshes rather than doing nothing.
5. Press Quick Export on Texture Set Output for the first time, configure a destination, and confirm the texture set exports.
6. Press Quick Export again and confirm no setup dialog appears.
7. Repeat the first-use and immediate Quick Export workflow on Single Image Output.
8. Save and reopen the graph; confirm both output types remember their quick-export destination and folder checkbox.
8. Use Configure Export and confirm the new destination and profile set are used and saved.
9. Open Export Outputs twice and confirm its folder-opening checkbox remembers the previous state.
10. Connect one Material to multiple Texture Set Outputs and batch-export different presets.
11. Connect Colour, Greyscale and Vector branches to Single Image Output and confirm Auto encoding follows semantic type.
12. Connect Flipbook Generator to Single Image Output and export the atlas.
13. Add nodes to favourites and confirm the ★ Favourites category appears at the top of the unfiltered Node Library.
