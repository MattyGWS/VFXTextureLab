# Levels

Levels remaps the tonal range of a greyscale, colour, or vector image while preserving its semantic data type.

## Five controls

- **Level In Low** maps the selected input low point to normalized black.
- **Level In High** maps the selected input high point to normalized white.
- **Level In Mid** is the normalized position between input low and high that maps to middle grey. `0.5` is neutral.
- **Level Out Low** is the value produced by normalized black.
- **Level Out High** is the value produced by normalized white.

Swapping the two output values inverts the result without changing the input range.

## Histogram interface

The three upper handles adjust input low, midpoint, and input high. The two lower handles adjust output low and output high. Use the toolbar button to switch to precise numerical sliders; scalar animation sockets are exposed from the slider interface.

The histogram is evaluated from the node's actual upstream branch at an interactive resolution. On colour or vector inputs, the channel selector controls which channel is displayed and used by Auto Level.

The graph uses a conventional **linear-frequency** display: each bin's height is directly proportional to the number of sampled pixels in that value range. Analysis uses 1024 internal bins before population-preserving reduction to the panel width. Values outside 0–1 are shown as slim edge indicators rather than being folded into the endpoint bins, and half-bin padding lets the visible distribution return to zero cleanly at each boundary.

## Quick actions

- **Auto Level** sets input low and input high once from the lowest and highest values currently present in the selected histogram channel. Later upstream changes do not automatically move the handles.
- **Invert** swaps output low and output high.
- **Histogram / Sliders** switches between visual and exact editing.

## Intermediary clamp

- **Clamp** restricts the transformed input to `0–1` before the output range is applied.
- **Passthrough** keeps the linear extension outside the input range until the output mapping stage. This is useful for floating-point data workflows.

## Shared editor behaviour in 0.15.1

The Levels histogram now participates in the shared visual-editor interaction contract. A selected handle can be nudged with Left/Right, **Shift** provides fine movement, Reset restores neutral Levels and intermediary clamping, and one continuous drag is recorded as one undo command while retaining debounced live preview updates.
