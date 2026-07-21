from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def scalar(definition, parameters, context: EvalContext) -> np.ndarray:
    return definition.evaluator({}, parameters, context)[..., 0]


def neighbour_energy(image: np.ndarray) -> float:
    dx = np.abs(image[:, 1:] - image[:, :-1]).mean()
    dy = np.abs(image[1:, :] - image[:-1, :]).mean()
    return float((dx + dy) * 0.5)


def main() -> int:
    registry = build_registry()
    context = EvalContext(160, 160)

    variation_ids = ("noise.billow", "noise.ridged", "noise.turbulence")
    images: dict[str, np.ndarray] = {}
    for type_id in variation_ids:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        images[type_id] = scalar(definition, parameters, context)
        assert np.isfinite(images[type_id]).all()
        assert float(images[type_id].std()) > 0.07

    # The three nodes must be genuinely distinct tools, not abs()/invert aliases.
    for index, first_id in enumerate(variation_ids):
        for second_id in variation_ids[index + 1 :]:
            first = images[first_id]
            second = images[second_id]
            mean_difference = float(np.mean(np.abs(first - second)))
            correlation = float(np.corrcoef(first.ravel(), second.ravel())[0, 1])
            assert mean_difference > 0.12, (first_id, second_id, mean_difference)
            assert abs(correlation) < 0.75, (first_id, second_id, correlation)

    ridged = registry.get("noise.ridged")
    params = ridged.default_parameters()
    baseline = scalar(ridged, params, context)
    params["ridge_sharpness"] = 6.0
    sharper = scalar(ridged, params, context)
    assert float(np.mean(np.abs(baseline - sharper))) > 0.04

    billow = registry.get("noise.billow")
    params = billow.default_parameters()
    baseline = scalar(billow, params, context)
    params["puffiness"] = 4.5
    params["softness"] = 0.1
    changed = scalar(billow, params, context)
    assert float(np.mean(np.abs(baseline - changed))) > 0.04

    turbulence = registry.get("noise.turbulence")
    params = turbulence.default_parameters()
    warped = scalar(turbulence, params, context)
    params["warp_strength"] = 0.0
    unwarped = scalar(turbulence, params, context)
    assert float(np.mean(np.abs(warped - unwarped))) > 0.04

    gaussian = registry.get("noise.gaussian")
    smooth_params = gaussian.default_parameters()
    smooth = scalar(gaussian, smooth_params, context)
    hard_params = dict(smooth_params)
    hard_params["smoothness"] = 0.0
    hard_params["detail"] = 0.0
    hard_params["disorder"] = 0.0
    hard = scalar(gaussian, hard_params, context)
    assert neighbour_energy(smooth) < neighbour_energy(hard) * 0.7, (
        neighbour_energy(smooth), neighbour_energy(hard)
    )
    assert float(np.mean(np.abs(smooth - hard))) > 0.05

    # All revised noises must remain exact temporal loops.
    for type_id in variation_ids + ("noise.gaussian",):
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        parameters["evolution"] = 0.0
        first = scalar(definition, parameters, context)
        parameters["evolution"] = 1.0
        last = scalar(definition, parameters, context)
        assert float(np.max(np.abs(first - last))) < 2.0e-5, type_id

    print(
        "Noise quality test passed: distinct billow/ridged/turbulence algorithms, "
        "weighted ridges, puffiness controls, domain-warped turbulence and smooth Gaussian fields"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
