# Testing 0.48.0 — Geometry Foundation

Use a fresh graph or add the following nodes to an existing test graph. Existing texture/material graphs should continue to behave exactly as they did in 0.47.0.6.

## 1. Typed graph behaviour

1. Add **Geometry Plane** and **Geometry Output**.
2. Confirm both use the new coral Geometry sockets/wire.
3. Connect Geometry Plane to Geometry Output.
4. Attempt to connect Geometry Plane to an image node such as Blend or Levels. The connection must be rejected.
5. Attempt to connect an image/noise output to Geometry Output. The connection must be rejected.
6. Insert a reroute on the Geometry wire and confirm it inherits the Geometry colour/type.
7. Optionally pass the mesh through Send/Receive and confirm the Receive output becomes Geometry.

## 2. Geometry Plane topology and UV controls

1. Focus Geometry Plane.
2. Confirm the 3D Preview shows a neutral shaded plane rather than the normal selected preview primitive.
3. Change Width and Height and confirm the plane dimensions update.
4. Change Subdivisions X/Y and confirm the status line reports the expected vertex/triangle changes.
5. Test Horizontal XZ, Vertical XY and Vertical YZ. Faces should remain visible and correctly lit from their positive normal direction.
6. Connect the plane to a Material with an obvious checker/grid texture. Confirm UVs cover the complete 0–1 texture once and Material Tiling still works.

Useful counts:

- 1 × 1 subdivisions: 4 vertices, 2 triangles;
- 4 × 2 subdivisions: 15 vertices, 16 triangles;
- default 16 × 16 subdivisions: 289 vertices, 512 triangles.

## 3. Preview override precedence

1. Focus Geometry Plane: its mesh should replace the viewport primitive with shaded inspection.
2. Focus an ordinary texture/noise node: the viewport should restore the selected standard mesh.
3. Connect Geometry Plane to the optional Geometry input on Material.
4. Focus Material: the current PBR material should render on the generated plane.
5. Disconnect Geometry from Material and refocus Material: the selected standard preview mesh should return.
6. Change the viewport mesh while no graph geometry override is active and confirm existing sphere/cube/cylinder/terrain behaviour is unchanged.

## 4. Geometry Output and OBJ export

1. Focus Geometry Output and confirm it previews the connected mesh.
2. In Parameters, choose **Export Geometry…** and save an OBJ.
3. Confirm the file contains vertex, UV, normal and face records and imports correctly in Blender or another OBJ reader.
4. Change **Include UV Coordinates**, **Include Vertex Normals** and **Flip UV V Coordinate**, exporting each variation.
5. After the first configured export, change plane subdivisions and use **Quick Export**. Confirm the same file is overwritten with the new topology.
6. Save/reopen the graph and confirm the Geometry connection and remembered export path remain intact.

## 5. Graph assets and portability

1. Create a child graph with Geometry Graph Input connected to Geometry Graph Output.
2. Import it as a Graph Instance in a parent graph.
3. Confirm its sockets are Geometry and the input is reported as required.
4. Pass Geometry Plane through the instance into Geometry Output or Material.
5. Save/reopen and, optionally, package the parent graph. Confirm the nested geometry interface remains valid.

## 6. Regression sweep

- Open a pre-0.48 texture/material graph and verify 2D Preview, 3D Preview, Material composition, Texture Set Output and Quick Export.
- Switch among all existing 3D preview meshes and test displacement, material tiling and camera controls.
- Exercise normal typed connections, reroutes, Send/Receive and graph assets for Colour, Greyscale, Vector / Normal, Material and signals.
- Confirm no geometry evaluation is submitted through the image/GPU node evaluator and no unexpected 2D thumbnail jobs appear for Geometry nodes.
