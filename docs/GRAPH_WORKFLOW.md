# Graph workflow

Version 0.15.0 adds direct graph-editing tools intended to keep large texture and animation graphs readable without interrupting construction. All structural edits participate in the normal undo/redo history.

## Previewing an exact output socket

Double-click a node body to preview its primary/default output. Double-click one output circle to lock the 2D Preview to that exact named result. The active socket receives a persistent highlight ring and the choice is saved with the graph. Material outputs also activate the complete 3D material; Signal outputs use the scalar presentation in the 2D panel.

Wire creation remains a press-and-drag gesture. The pointer must cross Qt's normal drag threshold before a temporary wire begins, so a double-click never leaves a dangling connection and a single click does not change the preview.

See [`GRAPH_EXPLORER.md`](GRAPH_EXPLORER.md) for multi-document graph authoring and live nested-graph workflows.

## Reroute dots

Reroutes are compact graph-only nodes. They perform no processing and inherit the exact type of the wire on which they are created: Greyscale, Colour, Vector, Scalar, Vector2 or Vector3. Their type, position and connections are saved in graph files and reusable groups.

Add a reroute using any of these methods:

- Double-click a wire at the desired position.
- Right-click a wire and choose **Add Reroute**.
- Hover a wire and press **R**, or select one wire and press **R**.

A reroute may feed more than one destination, making it useful as a clean branching point. Delete it like an ordinary selected node.

## Cutting wires

Hold **X**, then press and drag the left mouse button across the graph. A dashed red knife line follows the pointer and every intersected connection is highlighted. Release the mouse button to remove all highlighted wires as one undoable edit.

The gesture begins only from graph space rather than from a port, so normal connection dragging remains available while **X** is held accidentally.

## Search from a loose connection

Begin dragging from an input or output port, then release over empty canvas. The **Connect Node** search opens and lists only node definitions with a compatible port. Choosing a result creates it at the release position and connects it immediately.

Dragging from an output searches for a compatible input. Dragging backwards from an input searches for a compatible output. Nodes whose effective dynamic output type cannot safely be determined are excluded rather than creating an invalid connection.

## Insert a node directly on a wire

Drag a built-in node from the Node Library over a wire. When the node can be inserted unambiguously, the wire highlights blue. Drop it to change:

```text
Source → Destination
```

into:

```text
Source → New Node → Destination
```

A newly created node that is still completely unconnected can also be moved onto a compatible wire and released to insert it.

Direct insertion is intentionally restricted to nodes with one compatible primary input and one compatible output. Generators, outputs, multi-input combiners and other ambiguous nodes are left as normal drops.

## Alignment and distribution

Select two or more nodes or reroutes, then use **Edit → Arrange**:

- Align Left, Horizontal Centres or Right
- Align Top, Vertical Centres or Bottom
- Distribute Horizontally or Vertically

Distribution requires at least three selected items. The two outermost items remain fixed and the others are spaced evenly between them.

## Node bypass

Eligible processing nodes show a small power icon in their header. Click it, or select one eligible node and press **B**, to toggle bypass.

A bypassed node is dimmed and outlined with a dashed border. During evaluation, its sole input is passed directly to its sole output, so the node behaves as though its effect were absent while its connections and settings remain intact. Toggle it again to restore processing. The bypass state is saved with the graph.

Bypass is not offered where pass-through would be ambiguous or misleading, including generators, output nodes, graph helpers, missing nodes and processors without exactly one compatible input and output.

## Edge auto-pan while wiring

While dragging a connection, move the pointer near any edge of the graph viewport. The canvas pans continuously in that direction and accelerates as the pointer approaches the edge. Keep holding the wire and continue to the distant target; no zoom-out or interrupted drag is required.

## Individual testing checklist

1. Connect two image nodes, double-click the wire and confirm a typed reroute appears without changing the preview. Branch a second connection from the reroute, save, reopen and confirm it remains intact.
2. Create several connections, hold **X**, drag across them and confirm only crossed wires turn red and are removed together on release. Undo once and confirm all return.
3. Drag a wire from an output into empty graph space, choose a compatible result and confirm it is created and connected automatically. Repeat by dragging backwards from an input.
4. Drag a simple one-input/one-output processing node from the library onto a wire. Confirm the wire highlights, then confirm both replacement connections are created. Verify an incompatible or multi-input node does not highlight the wire.
5. Create a fresh unconnected processing node, move it over a compatible wire and release. Confirm it inserts. Connect it elsewhere first and verify moving it no longer rewires the graph automatically.
6. Select several nodes and exercise every **Edit → Arrange** command. Confirm alignment uses the requested edge or centre and distribution leaves the outer items fixed.
7. Insert a visible processing effect, click its power icon and confirm the output matches the upstream input. Confirm the node is visually dimmed, survives save/reopen, and returns to its authored effect when enabled.
8. Begin a wire drag and hold it near each canvas edge. Confirm the graph pans continuously while the temporary wire stays attached to the pointer.

## Docked utility nodes

Select an eligible node and press **D** to attach it compactly to the one downstream input it feeds. Press **D** again to restore it to its previous free graph position.

A node can dock when it has one output, no more than one visible input, and exactly one downstream connection. Docking only changes presentation: selection, Parameters, double-click preview, bypass, deletion, copy/paste, undo/redo and evaluation continue to use the original node and connection.

Docking may be nested. A compact node can itself receive another compact node, producing a short local processing chain beside the final parent input. Creating a second outgoing connection, removing the parent connection, or making that connection invalid automatically undocks the node.

## Send and Receive portals

**Send** and **Receive** live in **Graph Utilities**. Connect a value to Send, give the Send a unique channel name, then choose that channel from one or more Receive nodes. Receives link to the Send by stable node identity, so renaming the Send updates every receiver without breaking the route.

Portals carry Greyscale, Colour, Vector / Normal, Material, Scalar, Vector2 and Vector3 types. Their sockets update to the published type. Selecting either endpoint temporarily draws faint dashed channel guides for debugging.

If the published type changes and an existing Receive output no longer matches its downstream input, the wire is retained as a dashed red inactive connection. It is excluded from evaluation but automatically becomes active again when the types match. Missing Sends, unconnected Sends and wireless cycles are shown directly as node errors.
