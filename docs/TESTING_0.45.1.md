# VFX Texture Lab 0.45.1 testing checklist

Version 0.45.1 extends the existing Export Outputs workflow with graph-local production profile sets, multiple targets per publish, target-specific overrides, expanded naming variables and shared graph evaluation.

## 1. Existing workflow remains unchanged by default

Open a 0.45.0/0.45.0.1 graph and choose **File → Export Outputs…**.

Confirm that:

- The default profile is **Current Output Settings**.
- It contains one enabled **Current Output** target.
- The target uses **Current node template** and exports into the selected root folder.
- Generic PBR Separate, Unreal ORM and custom templates produce the same files as before.
- Single Image Outputs still export exactly once using their own settings.

## 2. Create a multi-target profile

In Export Outputs:

1. Press **New…** and call the profile `Unreal + Source`.
2. Edit the first target and name it `Unreal Production`.
3. Choose **Unreal ORM**, subfolder `{target}`, DirectX normals, 1024 × 1024 and 8-bit data.
4. Add another target named `Source Archive`.
5. Choose **Generic PBR Separate**, subfolder `{target}`, 2048 × 2048, 16-bit colour and 16-bit scalar data.

Select a Texture Set Output and confirm Planned Files shows both folders and both target layouts before evaluation.

Export and verify a structure similar to:

```text
Unreal_Production/
  Material_BaseColor.png
  Material_Normal.png
  Material_Height.png
  Material_ORM.png
Source_Archive/
  Material_BaseColor.png
  Material_Normal.png
  Material_Height.png
  Material_AO.png
  Material_Roughness.png
  Material_Metallic.png
```

## 3. Target controls

Test each target-level override independently:

- Current node template versus a selected built-in template.
- Output setting versus an explicit resolution.
- OpenGL (+Y) versus DirectX (-Y).
- PNG versus TGA.
- 8-bit versus 16-bit colour.
- 8-bit versus 16-bit scalar maps.
- PNG 16-bit versus Raw R16 Height.

Confirm **Output setting** inherits the Texture Set Output node and an explicit target value affects only that target.

## 4. Profile management

Test:

- New profile.
- Duplicate profile.
- Rename profile.
- Delete profile.
- Add, edit, duplicate and remove targets.
- Disable one target with its checkbox.

The Planned Files list should update immediately. A profile cannot delete its final target, and export should refuse to proceed when a selected Texture Set Output has no enabled target.

Cancel the dialogue after making temporary changes and reopen it. The cancelled changes should be gone.

Accept/export after making changes, save the graph, close and reopen it. Every profile, target, checkbox and override should remain intact.

## 5. Expanded naming variables

Use the Texture Set Output file pattern:

```text
{graph}_{version}_{profile}_{target}_{set}_{map}_{width}x{height}
```

Give the graph a clear Graph Properties name and version. Confirm every token resolves in Planned Files and on disk.

Test target subfolders such as:

```text
{graph}/{profile}/{target}
```

Unsupported subfolder tokens, absolute paths and `..` should be rejected by the target editor.

## 6. Several output nodes

Create two Texture Set Outputs with different set names and select both. The same enabled targets should be applied to both nodes.

Add one Single Image Output to the selection. Confirm:

- Both texture sets are exported through every enabled target.
- The Single Image Output is written once, not once per target.
- Planned Files reports any genuine path collision before export.

## 7. Shared evaluation

Use an expensive Material branch, preferably erosion or a nested graph, and create two targets at the same resolution.

Export both and inspect the progress messages/Evaluation Inspector. The source channels should be evaluated once per output and resolution, followed by several packing/writing steps.

Change one target to another resolution. That target should require its own source evaluation, while targets sharing the first resolution continue to reuse theirs.

## 8. Quick Export profile memory

Configure Quick Export on a Texture Set Output using the `Unreal + Source` profile.

Confirm the Inspector shows the profile name. Press Quick Export again and verify both targets export without reopening setup.

Then edit or switch the graph's currently active profile and press Quick Export again. It should continue using the complete profile snapshot saved for that output until **Configure Export…** is used to replace it.

Save and reopen the graph and repeat the immediate Quick Export.

## 9. Persistence and portability

Save a graph containing several profile sets and pass it through:

- Export Self-Contained Graph.
- Export VFX Package.
- Open package temporarily.
- Extract as editable project.
- Install as a Graph Asset.

The profile sets and targets should remain available in every copy without sidecar files.

## 10. Regression checks

- Built-in and custom export templates still work.
- Scalar PNG/R16 outputs no longer produce channel-index errors.
- Normal Y inversion remains target-specific.
- Replace existing, Add numeric suffix and Skip existing still work in target subfolders.
- Stable collision suffixes retain the intended target folder.
- Cancelled exports leave already completed files intact and do not corrupt graph/profile data.
