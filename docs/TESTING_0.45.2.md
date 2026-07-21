# VFX Texture Lab 0.45.2 — Sharing and Packages testing

## 1. Export a template

1. Select a Texture Set Output and open **Customise Template…**.
2. Enter a name, description, author, version and engine/purpose.
3. Press **Export .vfxexport…** and save the file.
4. Reopen the editor, press **Import .vfxexport…**, and confirm all files, channels and metadata return unchanged.
5. Confirm the imported template remains graph-local after saving and reopening the `.vfxgraph`.

## 2. Install and use a user template

1. In the editor press **Install in User Templates**, or use **Library → Install Export Template…**.
2. Open **Library → User Export Templates…** and confirm the template shows its metadata and source path.
3. Open Export Outputs, create/edit a target, and select the installed template.
4. Export and confirm the target uses the imported channel layout.
5. Remove the installed template from the manager. Reopen the graph and confirm the target still works from its graph-local snapshot.

## 3. Stable-ID conflicts

1. Export a template and install it.
2. Change its description or file layout without generating a new Template ID, increase its version, and install it again.
3. Test **Update Installed** and confirm the existing user-library entry is replaced.
4. Repeat and choose **Install Side by Side**. Confirm both entries remain and the incoming copy receives a separate identity.
5. Confirm Cancel/Skip leaves the installed definition untouched.

## 4. Package inclusion

1. Create a graph with a custom Texture Set Output template and a multi-target profile using a user template.
2. Export a `.vfxpackage` with **Include graph-local export templates as shareable .vfxexport files** enabled.
3. Rename a disposable copy to `.zip` and confirm it contains `export_templates/*.vfxexport` plus manifest entries.
4. Open Package Details and confirm the included template names/versions are shown.
5. Extract as an editable project and confirm the `.vfxexport` files are available in the extracted folder.

## 5. Package installation

1. Install the package into the Graph Asset library.
2. Accept installation of its included export templates.
3. Confirm they appear in **User Export Templates** and in new export target/template-editor selectors.
4. Install the package again and test Update, Side by Side and Skip for template conflicts.
5. Confirm declining template installation does not prevent the Graph Asset itself from installing; its embedded graph-local templates should still work.

## 6. Compact package

Export the same graph with template-file inclusion disabled. Confirm:

- No `export_templates/` members are present.
- The package still opens and exports correctly because graph-local definitions remain inside the graph.
- Package validation and hash/tamper protection still function.

## 7. Regression checks

- Built-in templates remain read-only starting points.
- Existing 0.45.0/0.45.1 custom templates open normally.
- Multi-target profiles, Quick Export and shared evaluation behave as before.
- Packages created before 0.45.2 still open and install.
- Library refreshes do not alter live graph wires or mark the graph dirty.
