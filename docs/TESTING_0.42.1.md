# VFX Texture Lab 0.42.1 Test Checklist

## Graph Asset Parameter dialogue

1. Open the starter graph and select **Ridge Noise**.
2. Confirm that no `…` button is shown beside **Octaves** before it is exposed.
3. Click the diamond button beside **Octaves** to expose it.
4. Confirm that the `…` button now appears.
5. Click `…` and verify that the dialogue opens with:
   - Public name: **Octaves**
   - Parameter group: **Parameters**
   - **Publish on Graph Instance nodes** enabled
6. Change the public name/group, accept, save the graph and use it as a Graph Instance. Confirm that the published control appears with the edited presentation.
7. Repeat with the exposed parameter connected internally. The metadata dialogue should still open, although an internally driven parameter remains private on Graph Instances.

## Conditional metadata controls

1. Inspect several ordinary numeric parameter rows.
2. Confirm that only the exposure diamond is present while the parameter is not exposed.
3. Expose and unexpose a parameter several times. The `…` button should appear and disappear with the exposed state.
4. Parameters explicitly marked as non-publishable should never show the `…` button.

## Clean Graph Explorer startup

1. Open several saved graphs, then close VFX Texture Lab cleanly.
2. Reopen it. A fresh starter graph should appear rather than the previous collection of saved graphs.
3. Enable **File → Defaults & Startup → Restore Open Graphs on Startup**.
4. Open several saved graphs, close and reopen the application. Those saved graphs should now be restored, with the previously active one selected where possible.
5. Disable the option again and verify that the following launch returns to a clean session.
6. Unsaved/dirty graphs should still prompt normally during application close; this change does not discard unsaved work.
