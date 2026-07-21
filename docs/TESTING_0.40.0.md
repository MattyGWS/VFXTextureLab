# VFX Texture Lab 0.40.0 manual test pass

This pass is intentionally focused on behaviour that automated numerical tests cannot fully judge: graph ergonomics, preview responsiveness, visual quality and export results.

## 1. Material Blend — basic coverage

1. Create two Material nodes with visibly different Base Colours and Roughness values.
2. Connect them to Background and Foreground on Material Blend.
3. Focus Material Blend and inspect both 2D and 3D previews.
4. Move Amount from 0 to 1.
5. Add a black-to-white mask and toggle Invert Mask.

Expected: Amount 0 is entirely Background; Amount 1 with a white mask is entirely Foreground; masked areas change all authored channels together; 2D shows the resolved Base Colour and 3D shows the complete material.

## 2. Height-aware layering

1. Give both source materials different Height textures.
2. Use a soft mid-grey/noise placement mask.
3. Switch Blend Method between Standard and Height Aware.
4. Adjust Height Influence, Transition Softness and Height Bias.

Expected: Standard follows the mask directly. Height Aware interlocks the boundary according to relative surface height without globally altering either heightmap. If both Height inputs are disconnected, Height Aware should behave like Standard rather than failing.

## 3. Advanced channel modes

- Compare Normal Crossfade with Combine Detail using two obvious normal maps.
- Compare Height Blend, Add Foreground Detail, Maximum and Minimum.
- Compare Emissive Blend and Add.

Expected: normals remain valid and do not become dark/flat RGB mixtures; Add Foreground Detail treats 0.5 as neutral height; Add emissive preserves background glow while adding foreground glow.

## 4. Material Override

1. Feed a complete Material into Material Override.
2. Connect only a new Roughness texture.
3. Confirm Base Colour, Normal and Height remain unchanged.
4. Add a mask and vary Amount.
5. Enable Remove Roughness, then connect Roughness to Material Channels and Texture Set Output.

Expected: only Roughness changes; masked-out pixels retain the original exactly; removal returns a 0.5 default when inspected but removes Roughness from the texture-set export plan. A connected override while removal is enabled should be reported as ignored.

## 5. Material settings inheritance

1. Set the source Material to Alpha Cutout or Additive and change its displacement/normal settings.
2. Pass it through Blend and Override.
3. Change Material Settings Source on Blend.
4. Enable Override Material Settings on Material Override.

Expected: Blend inherits settings from the chosen source; Override inherits the incoming settings until its settings override is enabled; no texture channel is baked or unexpectedly modified by these preview settings.

## 6. Material Channels

1. Connect a composed material to Material Channels.
2. Preview Base Colour, Normal, Height and Roughness individually.
3. Feed several outputs into normal image-processing nodes.
4. Leave one source channel absent and inspect its output.

Expected: every socket has the correct type colour; downstream nodes work normally; absent maps show their documented semantic defaults; using one output should not visibly trigger unrelated channel work in the Evaluation Inspector.

## 7. Material Switch and animation

1. Connect two very different complete materials to A and B.
2. Toggle Selected Material.
3. Connect Loop Phase to Selection and use a 0.5 Threshold.
4. Press Play.

Expected: the entire material switches at the threshold, including settings and all maps. It should not crossfade. The Evaluation Inspector should show only the selected material branch being evaluated.

## 8. Portals, docking and persistence

1. Send a Material Blend or Override through a named Send/Receive pair.
2. Feed Receive into Material Channels and Texture Set Output.
3. Dock eligible utility nodes around the material graph.
4. Save, close and reopen the graph.

Expected: the Receive remains purple/Material typed; previews and export still resolve correctly; all node parameters, channel removals, portal links and connections survive reopening.

## 9. Texture-set export

1. Export a composed material as Separate PBR maps.
2. Try Unreal ORM or Unity HDRP Mask Map.
3. Remove one channel with Material Override and export again.
4. Compare exported images with Material Channels previews.

Expected: exported values match the composed material; packed maps use the final composed channels; genuinely absent/removed separate maps are omitted; normal convention conversion still works.

## 10. Responsiveness and failure cases

Try the above at 512, 2K and, where practical, 4K. Rapidly edit masks and Amount while 2D and 3D previews are visible. Also test one missing Material Blend input, a Material Switch pointing at an unconnected selected input and a portal whose Send is deleted.

Expected: no crash, black preview or stale material; clear warnings for missing selections/connections; ordinary graph editing remains responsive and final-quality previews settle on the newest value.
