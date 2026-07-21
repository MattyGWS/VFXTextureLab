# VFX Texture Lab 0.45.0 testing checklist

Version 0.45.0 converts Texture Set Output into a reusable export-template system while retaining the existing batch and Quick Export workflow.

## 1. Existing built-in templates

Create one Material with Base Colour, Normal, Height, AO, Roughness, Metallic, Emissive and Opacity connected. Feed it into several Texture Set Output nodes.

Test each template:

- **Generic PBR Separate** writes separate BaseColor, Normal, Emissive, Opacity, Height, AO, Roughness, Metallic and Specular files only where the semantic source is present.
- **Unreal ORM** writes AO to R, Roughness to G and Metallic to B.
- **Unity HDRP Mask Map** writes Metallic to R, AO to G, Constant 1 to B and Smoothness (`1 - Roughness`) to A.
- **Godot ORM** writes AO/Roughness/Metallic to R/G/B.
- **VFX RGBA Masks** uses Opacity R, Emissive luminance G, Height B and AO A.

Confirm that changing between built-ins immediately changes the planned file list without changing the Material graph.

## 2. Customise a built-in

Select a Texture Set Output and expand **Template Editor** in the Inspector.

1. Choose Unreal ORM.
2. Press **Customise Template…**.
3. Select the ORM file.
4. Swap Roughness and Metallic between G and B.
5. Press **Use Custom Template**.

Confirm that:

- Export template changes to **Custom Template**.
- The Inspector summary shows the custom template name and file count.
- Export Outputs previews the altered packed file.
- Exporting produces the exact changed channel arrangement.
- Undo restores the built-in selection and redo restores the custom template.

## 3. Create a VFX packed file

In the editor:

1. Remove all files.
2. Add one output.
3. Name it `VFX Packed` and set `{map}` to `VFX`.
4. Choose RGBA, PNG, 8-bit and Linear.
5. Assign R = Opacity, G = Emissive Luminance, B = Height and A = Ambient Occlusion.
6. Toggle Invert on any one channel.

Export and inspect the channels externally. Confirm the inverted channel is numerically inverted and the others retain their authored values.

## 4. Source component choices

Test assignments from:

- Base Colour Red, Green, Blue, Alpha and Luminance.
- Emissive components and Luminance.
- Normal Red, Green/Y and Blue.
- Scalar material channels.
- Constant 0 and Constant 1.

A file with only constants is normally skipped unless **Write this file even when every assigned source is absent** is enabled.

## 5. Normal conventions

Create a custom RGB normal file using Normal Red, Normal Green/Y convention and Normal Blue.

- Export using **OpenGL (+Y)** and record the Green channel.
- Switch the output node to **DirectX (-Y)** and export again.

Only Green/Y should invert. Red and Blue must remain unchanged. Adding the channel's explicit Invert option should intentionally cancel or compound that convention change.

## 6. Formats and depth

Check:

- PNG 8-bit and 16-bit.
- TGA, which should always write 8-bit.
- Raw R16, which should force Grayscale, Linear and 16-bit.
- **Texture-set setting**, which follows Image format and the colour/scalar depth controls on the node.
- **Height setting**, which follows the node's PNG 16-bit / Raw R16 Height format control.

Export Height at 8-bit deliberately and confirm Export Outputs shows a warning before writing.

## 7. Per-file names and tokens

Leave one file using the Texture Set Output node pattern and give another a custom pattern.

Test:

- `{set}`
- `{map}`
- `{output}`
- `{width}`
- `{height}`

Invalid or unsupported custom-template tokens should prevent the editor from accepting the template. Existing graph-level naming and stable collision disambiguation should still work.

## 8. Planned Files preflight

Open **File → Export Outputs…** with multiple output nodes selected.

Confirm the Planned Files list shows:

- Fully resolved filename.
- PNG/TGA/R16 format.
- Effective bit depth.
- Grayscale/RGB/RGBA layout.
- sRGB or Linear handling.
- Resolution.
- Warnings from the template.

Select two outputs that resolve to the same filename. Both entries should receive a warning, and the existing safe-name confirmation should still appear before export.

## 9. Persistence and portability

Create a custom template, save the graph, close and reopen it.

Confirm the entire file list and every channel assignment survive. Then test:

- Export Self-Contained Graph.
- Export VFX Package.
- Open the package temporarily.
- Extract it as an editable project.
- Install it as a Graph Asset.

The graph-local custom template should remain intact in every case without requiring a separate template file.

## 10. Legacy graph migration

Open a 0.44.x graph whose Texture Set Output used **Separate PBR Maps**.

It should display **Generic PBR Separate** and plan the same files. Saving and reopening should remain stable.

## 11. Quick Export regression

Configure Quick Export for a Texture Set Output, then change or customise its template.

Quick Export should use the current template while retaining the saved destination, replacement policy and open-folder preference.
