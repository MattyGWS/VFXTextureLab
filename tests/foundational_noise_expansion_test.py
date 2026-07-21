from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


TYPE_IDS = (
    "noise.clouds_1", "noise.clouds_2", "noise.clouds_3",
    "noise.bnw_spots_1", "noise.bnw_spots_2", "noise.bnw_spots_3",
    "noise.crystal_1", "noise.crystal_2", "noise.fractal_sum",
    "noise.anisotropic", "noise.fibres", "noise.messy_fibres",
    "noise.moisture", "noise.fur",
)


def render(type_id: str, changes: dict | None = None, size: int = 96) -> np.ndarray:
    definition = build_registry().get(type_id)
    parameters = definition.default_parameters()
    parameters.update(changes or {})
    assert definition.evaluator is not None
    return definition.evaluator({}, parameters, EvalContext(size, size))[..., 0]


def assert_registry_and_backend_contract() -> None:
    registry = build_registry()
    for type_id in TYPE_IDS:
        definition = registry.get(type_id)
        assert definition.gpu_kernel == "foundational_noise.wgsl"
        assert definition.output_format == "r16f"
        assert definition.output_kind(definition.output_name) == "grayscale"
        assert definition.default_image_kind == "grayscale"
        assert definition.evaluator is not None

    root = Path(__file__).resolve().parents[1]
    backend_path = root / "vfx_texture_lab" / "engine" / "backends" / "wgpu_backend.py"
    backend_source = backend_path.read_text(encoding="utf-8")
    module = ast.parse(backend_source)
    shaders = None
    inputs = None
    for item in module.body:
        if isinstance(item, ast.ClassDef) and item.name == "WgpuBackend":
            for statement in item.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id == "_SHADERS":
                        shaders = ast.literal_eval(statement.value)
                    if isinstance(target, ast.Name) and target.id == "_INPUT_ORDER":
                        inputs = ast.literal_eval(statement.value)
    assert shaders is not None and inputs is not None
    for type_id in TYPE_IDS:
        assert shaders[type_id] == "foundational_noise.wgsl"
        assert inputs[type_id] == ()

    shader = (root / "vfx_texture_lab" / "shaders" / "foundational_noise.wgsl").read_text(encoding="utf-8")
    for token in (
        "directional_disorder", "cloud_disorder", "fractal_field",
        "value_fractal_field", "anisotropic_value_noise", "cell_spots", "sparse_spot_field", "segment_field",
        "cellular_fields_simple", "crystal_voronoi_distance", "crease_crystal_field",
        "support_fade", "variant == 13u", "textureStore(output_tex",
    ):
        assert token in shader


def assert_default_quality_and_distinction() -> None:
    images: dict[str, np.ndarray] = {}
    for type_id in TYPE_IDS:
        image = render(type_id)
        images[type_id] = image
        assert np.isfinite(image).all(), type_id
        assert image.min() >= 0.0 and image.max() <= 1.0, type_id
        assert float(image.std()) > 0.035, (type_id, float(image.std()))
        assert len(np.unique(np.round(image, 4))) > 500, type_id

    groups = (
        ("noise.clouds_1", "noise.clouds_2", "noise.clouds_3"),
        ("noise.bnw_spots_1", "noise.bnw_spots_2", "noise.bnw_spots_3"),
        ("noise.crystal_1", "noise.crystal_2"),
        ("noise.anisotropic", "noise.fibres", "noise.messy_fibres", "noise.fur"),
    )
    for group in groups:
        for index, first_id in enumerate(group):
            for second_id in group[index + 1 :]:
                first, second = images[first_id], images[second_id]
                difference = float(np.mean(np.abs(first - second)))
                correlation = float(np.corrcoef(first.ravel(), second.ravel())[0, 1])
                assert difference > 0.055, (first_id, second_id, difference)
                assert abs(correlation) < 0.82, (first_id, second_id, correlation)



def assert_cloud_character() -> None:
    clouds = {type_id: render(type_id, size=192) for type_id in TYPE_IDS[:3]}
    expected_ranges = {
        "noise.clouds_1": ((0.55, 0.72), (0.08, 0.18)),
        "noise.clouds_2": ((0.58, 0.78), (0.07, 0.16)),
        "noise.clouds_3": ((0.30, 0.55), (0.09, 0.22)),
    }
    for type_id, image in clouds.items():
        mean_range, std_range = expected_ranges[type_id]
        mean = float(image.mean())
        std = float(image.std())
        assert mean_range[0] <= mean <= mean_range[1], (type_id, mean)
        assert std_range[0] <= std <= std_range[1], (type_id, std)

    # Clouds 2 is intentionally the broadest/softest family member, while 1
    # and 3 retain substantially more fine structure.  This catches a return
    # to three similarly folded turbulence/billow variants.
    gradient_energy: dict[str, float] = {}
    for type_id, image in clouds.items():
        gradient_energy[type_id] = float(
            np.mean(np.abs(np.diff(image, axis=0)))
            + np.mean(np.abs(np.diff(image, axis=1)))
        )
    assert gradient_energy["noise.clouds_2"] < gradient_energy["noise.clouds_1"] * 0.55
    assert gradient_energy["noise.clouds_2"] < gradient_energy["noise.clouds_3"] * 0.55

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    cloud_section = source[source.index("def eval_clouds_1"):source.index("def _cell_spots")]
    assert cloud_section.count("_value_fractal_field") >= 9
    assert 'mode="billow"' not in cloud_section
    assert 'mode="turbulence"' not in cloud_section
    assert 'mode="ridged"' not in cloud_section



def assert_spot_character() -> None:
    spots = {type_id: render(type_id, size=192) for type_id in TYPE_IDS[3:6]}
    expected_ranges = {
        "noise.bnw_spots_1": ((0.31, 0.44), (0.12, 0.20)),
        "noise.bnw_spots_2": ((0.37, 0.51), (0.10, 0.19)),
        "noise.bnw_spots_3": ((0.42, 0.56), (0.08, 0.16)),
    }
    gradient_energy: dict[str, float] = {}
    for type_id, image in spots.items():
        mean_range, std_range = expected_ranges[type_id]
        mean = float(image.mean())
        std = float(image.std())
        assert mean_range[0] <= mean <= mean_range[1], (type_id, mean)
        assert std_range[0] <= std <= std_range[1], (type_id, std)
        gradient_energy[type_id] = float(
            np.mean(np.abs(np.diff(image, axis=0)))
            + np.mean(np.abs(np.diff(image, axis=1)))
        )

    # Spots 1 and 2 deliberately retain much more impulse/speckle energy than
    # the broad, softer Spots 3 variant.
    assert gradient_energy["noise.bnw_spots_1"] > gradient_energy["noise.bnw_spots_3"] * 2.4
    assert gradient_energy["noise.bnw_spots_2"] > gradient_energy["noise.bnw_spots_3"] * 2.4

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    spot_section = source[source.index("def eval_bnw_spots_1"):source.index("def _cellular_fields_simple")]
    assert spot_section.count("_sparse_spot_field") >= 9
    assert "_fractal_field(" not in spot_section
    assert 'mode="billow"' not in spot_section
    assert 'mode="turbulence"' not in spot_section
    assert 'mode="ridged"' not in spot_section


def assert_spot_continuity_and_crystal_character() -> None:
    # BnW Spots 3 is intentionally the softest member of the family.  The
    # sparse Gaussian support must end smoothly: a finite neighbour search
    # may not create cell-aligned derivative jumps that become dark seams when
    # the field is converted to a normal map.
    spot = render("noise.bnw_spots_3", size=256)
    spot_gradient = np.concatenate((
        np.abs(np.diff(spot, axis=0)).ravel(),
        np.abs(np.diff(spot, axis=1)).ravel(),
    ))
    assert float(np.quantile(spot_gradient, 0.9999)) < 0.055, float(
        np.quantile(spot_gradient, 0.9999)
    )
    assert float(spot_gradient.max()) < 0.070, float(spot_gradient.max())

    registry = build_registry()
    crystal_1_definition = registry.get("noise.crystal_1")
    crystal_2_definition = registry.get("noise.crystal_2")
    crystal_1_names = [parameter.name for parameter in crystal_1_definition.parameters]
    assert crystal_1_names == [
        "scale_x", "scale_y", "seed", "evolution", "loop_cycles",
        "contrast", "balance", "invert",
    ], crystal_1_names
    crystal_2_labels = [parameter.label for parameter in crystal_2_definition.parameters]
    crystal_2_names = [parameter.name for parameter in crystal_2_definition.parameters]
    assert len(crystal_2_labels) == len(set(crystal_2_labels)), crystal_2_labels
    assert crystal_2_labels.count("Disorder") == 1, crystal_2_labels
    assert not {"disorder_scale", "disorder_anisotropy", "disorder_angle"}.intersection(crystal_2_names)

    crystal_1 = render("noise.crystal_1", size=256)
    crystal_2 = render("noise.crystal_2", size=256)

    # Crystal 1 follows the compact dual-Voronoi ratio construction: mostly
    # dark planar facets with sparse bright junctions, not white cell centres.
    assert 0.085 <= float(crystal_1.mean()) <= 0.145, float(crystal_1.mean())
    assert 0.070 <= float(crystal_1.std()) <= 0.125, float(crystal_1.std())
    assert 0.18 < float(np.quantile(crystal_1, 0.90)) < 0.32
    assert 0.32 < float(np.quantile(crystal_1, 0.99)) < 0.55
    stretched = render("noise.crystal_1", {"scale_x": 8, "scale_y": 28}, size=256)
    gradient_x = float(np.mean(np.abs(np.diff(stretched, axis=1))))
    gradient_y = float(np.mean(np.abs(np.diff(stretched, axis=0))))
    assert gradient_y > gradient_x * 1.6, (gradient_x, gradient_y)

    # Crystal 2 is a restrained, mid-grey cloth/crease field.  With the
    # default vertical fold direction its gradients should be predominantly
    # horizontal, catching a return to short isotropic line segments.
    assert 0.400 <= float(crystal_2.mean()) <= 0.570, float(crystal_2.mean())
    assert 0.060 <= float(crystal_2.std()) <= 0.160, float(crystal_2.std())
    gradient_x = float(np.mean(np.abs(np.diff(crystal_2, axis=1))))
    gradient_y = float(np.mean(np.abs(np.diff(crystal_2, axis=0))))
    assert gradient_x > gradient_y * 1.8, (gradient_x, gradient_y)

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    crystal_section = source[source.index("def _crystal_voronoi_distance"):source.index("def eval_fractal_sum")]
    assert "_crystal_voronoi_distance" in crystal_section
    assert "np.sqrt" in crystal_section
    assert "np.minimum" in crystal_section and "np.maximum" in crystal_section
    assert "_crease_crystal_field" in crystal_section
    assert "_angular_crystal_field" not in crystal_section


def assert_anisotropic_character_and_parameters() -> None:
    definition = build_registry().get("noise.anisotropic")
    parameter_names = [parameter.name for parameter in definition.parameters]
    assert parameter_names == [
        "scale_x", "scale_y", "smoothness", "interpolation",
        "seed", "evolution", "loop_cycles",
    ], parameter_names

    image = render("noise.anisotropic", size=256)
    gradient_x = float(np.mean(np.abs(np.diff(image, axis=1))))
    gradient_y = float(np.mean(np.abs(np.diff(image, axis=0))))
    # The defining feature is long horizontal value-noise strips: luminance
    # changes many times vertically but only gradually along their length.
    assert gradient_y > gradient_x * 2.4, (gradient_x, gradient_y)
    assert 0.42 <= float(image.mean()) <= 0.58
    assert 0.14 <= float(image.std()) <= 0.24

    # Both artist controls must have distinct, visible jobs.
    crisp = render("noise.anisotropic", {"smoothness": 0.05}, 128)
    smooth = render("noise.anisotropic", {"smoothness": 1.0}, 128)
    linear = render("noise.anisotropic", {"interpolation": 0.0}, 128)
    hermite = render("noise.anisotropic", {"interpolation": 1.0}, 128)
    assert float(np.mean(np.abs(crisp - smooth))) > 0.035
    assert float(np.mean(np.abs(linear - hermite))) > 0.008

    dense_y = render("noise.anisotropic", {"scale_y": 96}, 128)
    broad_y = render("noise.anisotropic", {"scale_y": 12}, 128)
    dense_energy = float(np.mean(np.abs(np.diff(dense_y, axis=0))))
    broad_energy = float(np.mean(np.abs(np.diff(broad_y, axis=0))))
    assert dense_energy > broad_energy * 2.0, (dense_energy, broad_energy)

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    section = source[source.index("def _anisotropic_value_noise"):source.index("def eval_fibres")]
    assert "_segment_field(" not in section
    assert "_fractal_field(" not in section
    for legacy_name in (
        "lines_number", "stretch", "width", "angle", "angle_random",
        "luminance_random", "disorder", "contrast", "balance", "invert",
    ):
        assert legacy_name not in parameter_names



def assert_moisture_character_and_parameters() -> None:
    definition = build_registry().get("noise.moisture")
    parameter_names = [parameter.name for parameter in definition.parameters]
    assert parameter_names == [
        "scale", "pool_size", "fine_detail", "patchiness", "disorder",
        "seed", "evolution", "loop_cycles", "contrast", "balance", "invert",
    ]
    for obsolete in (
        "pattern_size_x", "pattern_size_y", "angle", "softness",
        "global_opacity", "disorder_scale", "disorder_anisotropy", "disorder_angle",
    ):
        assert obsolete not in parameter_names

    image = render("noise.moisture", size=192)
    assert 0.45 <= float(image.mean()) <= 0.60
    assert 0.09 <= float(image.std()) <= 0.18

    # Fine Detail must add genuine high-frequency condensation specks rather
    # than merely changing the contrast of the broad patch field.
    quiet = render("noise.moisture", {"fine_detail": 0.0}, 192)
    detailed = render("noise.moisture", {"fine_detail": 1.0}, 192)
    quiet_energy = float(np.mean(np.abs(np.diff(quiet, axis=0))) + np.mean(np.abs(np.diff(quiet, axis=1))))
    detail_energy = float(np.mean(np.abs(np.diff(detailed, axis=0))) + np.mean(np.abs(np.diff(detailed, axis=1))))
    assert detail_energy > quiet_energy * 1.06, (quiet_energy, detail_energy)

    for changes in ({"pool_size": 2.2}, {"patchiness": 0.0}, {"disorder": 1.2}):
        altered = render("noise.moisture", changes, 160)
        assert float(np.mean(np.abs(image[:160, :160] - altered))) > 0.01

    root = Path(__file__).resolve().parents[1]
    source = (root / "vfx_texture_lab" / "nodes" / "noise_expansion.py").read_text(encoding="utf-8")
    section = source[source.index("def eval_moisture_noise"):source.index("def eval_fur")]
    assert "_cell_spots(" not in section
    assert section.count("_sparse_spot_field(") == 4
    assert "_value_fractal_field(" in section


def assert_seed_loop_and_controls() -> None:
    for type_id in TYPE_IDS:
        first = render(type_id, {"seed": 123, "evolution": 0.0}, 64)
        repeated = render(type_id, {"seed": 123, "evolution": 0.0}, 64)
        changed = render(type_id, {"seed": 124, "evolution": 0.0}, 64)
        looped = render(type_id, {"seed": 123, "evolution": 1.0}, 64)
        assert np.array_equal(first, repeated), type_id
        assert float(np.mean(np.abs(first - changed))) > 0.005, type_id
        assert float(np.max(np.abs(first - looped))) < 3.0e-5, type_id

    checks = (
        ("noise.clouds_2", {"puffiness": 3.6}),
        ("noise.bnw_spots_1", {"grain": 0.05}),
        ("noise.crystal_2", {"angle": 107.0}),
        ("noise.fractal_sum", {"min_level": 4, "max_level": 9}),
        ("noise.anisotropic", {"scale_y": 73, "smoothness": 0.25}),
        ("noise.fibres", {"length": 0.35}),
        ("noise.messy_fibres", {"messiness": 2.6}),
        ("noise.moisture", {"pool_size": 2.1, "fine_detail": 0.1}),
        ("noise.fur", {"angle_random": 115.0}),
    )
    for type_id, changes in checks:
        baseline = render(type_id, size=80)
        altered = render(type_id, changes, 80)
        difference = float(np.mean(np.abs(baseline - altered)))
        assert difference > 0.01, (type_id, difference)


def assert_optional_gpu_execution() -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        print("Focused Foundational Noise GPU comparison skipped:", gpu.info().detail)
        return
    cpu = CpuBackend(gpu)
    registry = build_registry()
    context = RenderContext(47, 41, TextureFormat.RGBA16F)
    loose = {
        "noise.crystal_1", "noise.crystal_2", "noise.anisotropic",
        "noise.messy_fibres",
    }
    for type_id in TYPE_IDS:
        definition = registry.get(type_id)
        parameters = definition.default_parameters()
        cpu_image = cpu.evaluate_node(definition, {}, parameters, context, f"cpu:{type_id}").array
        gpu_image = gpu.to_cpu(
            gpu.evaluate_node(definition, {}, parameters, context, f"gpu:{type_id}")
        ).array
        difference = np.abs(cpu_image - gpu_image)
        assert np.isfinite(gpu_image).all(), type_id
        if type_id == "noise.fibres":
            assert float(difference.mean()) < 0.03, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.18, (type_id, difference.mean(), difference.max())
        elif type_id in {"noise.bnw_spots_1", "noise.bnw_spots_2", "noise.bnw_spots_3", "noise.moisture"}:
            assert float(difference.mean()) < 0.025, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.11, (type_id, difference.mean(), difference.max())
        elif type_id in loose:
            assert float(difference.mean()) < 0.006, (type_id, difference.mean(), difference.max())
            assert float(np.quantile(difference, 0.95)) < 0.02, (type_id, difference.mean(), difference.max())
        else:
            assert float(difference.max()) < 0.002, (type_id, difference.mean(), difference.max())


def main() -> int:
    assert_registry_and_backend_contract()
    assert_default_quality_and_distinction()
    assert_cloud_character()
    assert_spot_character()
    assert_spot_continuity_and_crystal_character()
    assert_anisotropic_character_and_parameters()
    assert_moisture_character_and_parameters()
    assert_seed_loop_and_controls()
    assert_optional_gpu_execution()
    print(
        "Foundational Noise Expansion test passed: cloud, sparse-spot, crystal, anisotropic and "
        "moisture character regressions, 14 distinct looping generators, artist controls, deterministic "
        "seeds, WGSL contracts and focused CPU/GPU agreement"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
