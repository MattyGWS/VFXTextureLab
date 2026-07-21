# Testing VFX Texture Lab 0.47.0.3

## 0.47.0.3 focused checks

### BnW Spots 3 continuity

1. Create **BnW Spots 3** at 512 or 1024.
2. Connect it to **Height to Normal** and raise the normal strength.
3. Inspect the result at 1:1 and Tile 3×3.
4. The normal should contain only the organic spot gradients. There should be no horizontal/vertical cell grid or isolated hard lines.
5. Change Scale, Roughness, Fine Grain and Seed; continuity should remain stable.

### Crystal 1

1. Compare **Crystal 1** beside ordinary Voronoi and Worley noise.
2. Crystal 1 should be a dark angular field with planar facets and sparse sharp highlights, not a set of white radial cell centres.
3. Change Scale, Disorder and Facet Sharpness. Every control should visibly affect the intended structure.
4. Confirm there is exactly one parameter labelled **Disorder**.

### Crystal 2

1. View **Crystal 2** at its defaults and convert it to a normal map.
2. It should produce long, restrained triangular cloth/crease planes around mid-grey—not short blurred dashes.
3. Rotate Fold Direction and confirm the entire crease family changes direction.
4. Test Scale, Disorder, Fold Sharpness and Fold Strength.
5. Confirm there is exactly one parameter labelled **Disorder**.


## Node search and organisation

Search for each of the following and confirm it creates normally:

- Clouds 1, Clouds 2, Clouds 3
- BnW Spots 1, BnW Spots 2, BnW Spots 3
- Crystal 1, Crystal 2
- Fractal Sum
- Anisotropic Noise
- Fibres, Messy Fibres, Fur
- Moisture Noise

The cloud, spot, crystal and fractal nodes should appear under **Noise/Foundational**. Directional strand/moisture nodes should appear under **Noise/Structured**.

## Visual distinction

At defaults, compare each numbered family side by side. **Clouds 1** should read as fine layered wisps, **Clouds 2** as broad soft vapour masses, and **Clouds 3** as darker dense mottling. None should show the obvious curled ridges, rings or absolute-value folds associated with Turbulence or Billow. BnW Spots 1 should show strong multiscale black/white deposits, BnW Spots 2 should show broad mottling covered in dense fine speckles, and BnW Spots 3 should be the broadest and softest of the three. None should resemble ordinary FBM, billow, ridged or turbulence noise. Crystal 1 should read as many small peaked facets; Crystal 2 should read as larger crossing folds or angular creases.

Use the same Seed while comparing so differences come from the construction rather than unrelated random states.

## Core controls

- Clouds 1: move Softness from 0 to 1; the cloud remains wispy rather than turning into contour loops.
- Clouds 2: compare low and high Puffiness; broad masses should expand without becoming a billow/ridge pattern.
- Clouds 3: test Erosion and Fine Detail independently; Erosion should increase mottled breakup while Fine Detail changes only the finer scale.
- BnW Spots: reduce Fine Grain to remove the micro-deposit layer, then increase Roughness to strengthen the middle-sized spots. Compare all three with the same Seed.
- Crystal 2: rotate Fold Direction and vary Crease Strength.
- Fractal Sum: isolate low frequencies with Maximum Level 2, then high frequencies with Minimum Level 4.
- Anisotropic Noise: rotate Angle and increase Stretch.
- Fibres: change Length and Width.
- Messy Fibres: increase Messiness, then Breakage.
- Moisture: use unequal Pattern Size X/Y and rotate Pattern Angle.
- Fur: increase Angle Random and Length.

No control should appear inert across its useful range.

## Tiling

Enable **Tile 3×3** in the 2D Preview for every node. Opposite edges should join without a visible discontinuity. Directional strands may cross the boundary, but should continue periodically rather than terminate at the seam.

## Evolution

Set Loop Cycles to 1 and compare Evolution 0 with Evolution 1. They should match exactly. Scrub Evolution between them and confirm motion remains coherent rather than jumping between unrelated seeds.

## Resolution and performance

Test at 512, 1K and 2K. Scale should describe the same feature count at each resolution. The GPU badge should remain active and Evaluation Inspector should not report an unexpected CPU fallback or readback for these generators.

The strand-based nodes are intentionally more expensive than ordinary FBM because they evaluate many analytic features per pixel. Interactive edits should still use the normal preview scheduling and settle to the authored full-resolution result.

## Suggested material checks

- Clouds 2 → Levels → Height to Normal for rounded smoke or eroded rock forms.
- BnW Spots 1 → Histogram Select for granular masks.
- Crystal 2 → Directional Lighting for stylised folded highlights.
- Fractal Sum → Highpass to isolate a selected frequency band.
- Moisture → Overlay or Roughness for wet/dry breakup.
- Fibres/Messy Fibres/Fur → Directional Warp or Normal generation for fabric and hair detail.
