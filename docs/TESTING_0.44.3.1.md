# VFX Texture Lab 0.44.3.1 testing checklist

Version 0.44.3.1 preserves imported image source files inside `.vfxpackage` archives while keeping embedded fallback copies in the graph.

## 1. Default package export

1. Open a graph containing at least one Image Input loaded from an external PNG, JPEG, TGA, WebP, BMP or TIFF.
2. Use **File → Export VFX Package…**.
3. Confirm the options dialog appears and **Include source image files in the package** is enabled by default.
4. Export the package.

Expected:

- Export succeeds.
- The completion message reports at least one image source file.
- The source graph is not modified or marked dirty.
- Opening Package Details reports the included image source count.

## 2. Inspect the archive

Make a disposable copy, rename it from `.vfxpackage` to `.zip`, and inspect it with an archive manager.

Expected:

- The entry graph remains under `graphs/`.
- Original image bytes appear under `resources/images/`.
- The package manifest lists each image source with its size and SHA-256 hash.
- The graph itself still contains embedded image data for direct package opening.

## 3. Exact source preservation

Compare an image inside `resources/images/` with the original imported file.

Expected:

- The files are byte-for-byte identical.
- File type and sensible source filename are preserved.
- The image has not been resized, converted or recompressed.

## 4. Duplicate image use

Use the same external image in two or more Image Input nodes and export another package.

Expected:

- The image is stored once under `resources/images/`.
- The manifest records all Image Input uses against that one source record.
- Every node still renders correctly when the package is opened temporarily.

## 5. Filename collisions

Use two different images that share the same filename but come from different folders.

Expected:

- Both files are included.
- Neither overwrites the other.
- One receives a deterministic short hash suffix when required.

## 6. Temporary opening

Move or rename the original image files, then choose **Open Temporarily** on the package.

Expected:

- The graph still renders correctly from embedded fallback bytes.
- The temporary graph remains clean and unsaved.
- Saving requests a normal `.vfxgraph` destination.

## 7. Editable extraction and relinking

Choose **Extract as Editable Project…**, open the extracted graph, right-click an Image Input and choose **Use Included Package Source**.

Expected:

- The action is enabled because the source exists beside the extracted graph.
- The node switches from embedded mode to the extracted external image.
- Undo and redo restore the two states correctly.
- The graph continues to render identically.

## 8. Managed installation

Install the package into the Graph Asset library, open its source graph, and test **Use Included Package Source** there too.

Expected:

- Included resources remain inside the managed package directory.
- The action resolves the correct installed source.
- Moving or deleting the original author's image does not affect the installed asset.

## 9. Embedded-only option

Export once more with **Include source image files in the package** disabled.

Expected:

- The package remains valid and opens normally.
- No `image-source` files or `resources/images/` content appear.
- Package Details reports no separate image source files.
- The preference is remembered the next time the export options appear.

## 10. Tamper validation

Modify one file under `resources/images/` in a disposable package copy without updating the manifest.

Expected:

- VFX Texture Lab rejects the package with an integrity or size mismatch.
- No extraction or installation occurs.
