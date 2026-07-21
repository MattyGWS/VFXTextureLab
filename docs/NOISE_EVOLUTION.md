# Noise Evolution

VFX Texture Lab 0.17.6 treats **Evolution** as a normalised animation phase rather than an unrestricted offset.

## Recommended animation connection

Connect either of these directly to a noise node's exposed Evolution socket:

- **Time → Loop Phase**
- **Loop Phase → Phase**

Both produce a value from 0 up to 1 across the selected document loop. Evolution 0 and Evolution 1 produce the same texture when Loop Cycles is 1, so a rendered flipbook closes cleanly.

The Time node's **Seconds** and **Frame** outputs are not normalised phases. They remain useful when passed through Cycle or Remap first, but connecting them directly makes the phase repeat much faster.

## Motion changes in 0.17.6

- Evolution controls now display a 0–1 range.
- Old values outside 0–1 wrap to their equivalent phase when a development graph is loaded.
- The temporal lattice now uses four coherent states per loop instead of sixteen.
- Fractal, Ridged, Billow, Turbulence and Voronoi Fractal no longer accelerate higher octaves through increasingly fast temporal cycles.
- Gaussian fine detail follows the same temporal phase as its base field.
- White Noise defaults to four Evolution Steps instead of sixteen.

These changes preserve exact loop closure while making one document loop feel like one deliberate evolution rather than many rapid unrelated changes.

## Controls

**Evolution**
: Current normalised phase from 0 to 1.

**Loop Cycles**
: Number of temporal cycles traversed across Evolution 0–1. Keep this at 1 for the calmest single closed loop.

**Disorder**
: Spatially warps the noise domain. It changes the shape and movement character but does not replace Evolution.

**Evolution Steps** on White Noise
: Number of distinct random states blended during one loop. Lower values are calmer; higher values deliberately create faster-changing grain.

## Focused test

1. Create Fractal Noise and expose Evolution as an input.
2. Connect Time → Loop Phase to Evolution.
3. Set the document to 120 frames at 30 FPS.
4. Play the timeline and confirm the noise changes continuously rather than boiling rapidly.
5. Compare frame 0 and the loop endpoint; they should match.
6. Repeat with Ridged, Billow, Turbulence, Gaussian, Worley and Voronoi Fractal.
7. Raise Loop Cycles only when intentionally requesting faster motion.
