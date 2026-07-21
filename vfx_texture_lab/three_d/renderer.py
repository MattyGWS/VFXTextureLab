from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import numpy as np

try:
    import wgpu
except ImportError:  # pragma: no cover - CPU-only installations show a friendly panel error.
    wgpu = None  # type: ignore[assignment]

from ..engine.cache import CacheStats, MemoryLRU
from .environment import load_environment, mip_chain
from .meshes import MeshData, mesh_for_settings
from .settings import MATERIAL_DEFAULT_VALUES, MATERIAL_INPUTS, normalise_surface_mode, viewport_settings


MATERIAL_BINDINGS = MATERIAL_INPUTS
SCENE_FORMAT = "rgba16float"
SHADOW_FORMAT = "depth32float"
SHADOW_SIZE = 1536
AUTO_WIREFRAME_TRIANGLE_LIMIT = 250_000


@dataclass(slots=True)
class CameraState:
    yaw: float = math.radians(42.0)
    pitch: float = math.radians(34.0)
    distance: float = 3.2
    target_x: float = 0.0
    target_y: float = 0.0
    target_z: float = 0.0
    projection: str = "Perspective"

    @property
    def target(self) -> np.ndarray:
        return np.array((self.target_x, self.target_y, self.target_z), dtype=np.float32)

    def eye(self) -> np.ndarray:
        cp = math.cos(self.pitch)
        direction = np.array(
            (cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)),
            dtype=np.float32,
        )
        return self.target + direction * self.distance


@dataclass(slots=True)
class _TextureHandle:
    texture: Any
    view: Any
    width: int
    height: int
    mip_count: int = 1

    def release(self) -> None:
        try:
            self.texture.destroy()
        except Exception:
            pass


@dataclass(slots=True)
class _MaterialTextureSet:
    textures: dict[str, _TextureHandle]
    bytes_used: int
    channel_tokens: dict[str, str]

    def release(self) -> None:
        for texture in self.textures.values():
            texture.release()
        self.textures.clear()


@dataclass(slots=True)
class _GeometryBufferSet:
    vertex_buffer: Any
    index_buffer: Any
    bytes_used: int

    def release(self) -> None:
        for buffer in (self.vertex_buffer, self.index_buffer):
            destroy = getattr(buffer, "destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    pass
        self.vertex_buffer = None
        self.index_buffer = None


def _normalise(value: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(value))
    return value / max(length, 1e-8)


def _look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    forward = _normalise(target - eye)
    right = _normalise(np.cross(forward, up))
    actual_up = np.cross(right, forward)
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, :3] = right
    matrix[1, :3] = actual_up
    matrix[2, :3] = -forward
    matrix[0, 3] = -float(np.dot(right, eye))
    matrix[1, 3] = -float(np.dot(actual_up, eye))
    matrix[2, 3] = float(np.dot(forward, eye))
    return matrix


def _perspective(fov_y: float, aspect: float, near: float = 0.02, far: float = 100.0) -> np.ndarray:
    f = 1.0 / math.tan(fov_y * 0.5)
    matrix = np.zeros((4, 4), dtype=np.float32)
    matrix[0, 0] = f / max(aspect, 1e-6)
    matrix[1, 1] = f
    matrix[2, 2] = far / (near - far)
    matrix[2, 3] = (far * near) / (near - far)
    matrix[3, 2] = -1.0
    return matrix


def _orthographic(scale: float, aspect: float, near: float = -50.0, far: float = 50.0) -> np.ndarray:
    height = max(scale, 0.01)
    width = height * max(aspect, 1e-6)
    left, right = -width, width
    bottom, top = -height, height
    matrix = np.eye(4, dtype=np.float32)
    matrix[0, 0] = 2.0 / (right - left)
    matrix[1, 1] = 2.0 / (top - bottom)
    matrix[2, 2] = 1.0 / (near - far)
    matrix[0, 3] = -(right + left) / (right - left)
    matrix[1, 3] = -(top + bottom) / (top - bottom)
    matrix[2, 3] = near / (near - far)
    return matrix


def _matrix_bytes(matrix: np.ndarray) -> np.ndarray:
    # WGSL matrices are stored column-major.
    return np.asarray(matrix, dtype=np.float32).T.reshape(-1)


def _parse_colour(value: str, default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        return default
    try:
        return tuple(int(text[index : index + 2], 16) / 255.0 for index in range(0, 8, 2))  # type: ignore[return-value]
    except ValueError:
        return default


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _rgba_image(array: np.ndarray) -> np.ndarray:
    image = np.asarray(array, dtype=np.float32)
    if image.ndim == 2:
        image = np.stack((image, image, image, np.ones_like(image)), axis=2)
    elif image.ndim == 3 and image.shape[2] == 1:
        scalar = image[..., 0]
        image = np.stack((scalar, scalar, scalar, np.ones_like(scalar)), axis=2)
    elif image.ndim == 3 and image.shape[2] == 3:
        image = np.concatenate((image, np.ones((*image.shape[:2], 1), dtype=np.float32)), axis=2)
    if image.ndim != 3 or image.shape[2] < 4:
        raise ValueError(f"Invalid material image: {image.shape}")
    return np.ascontiguousarray(np.clip(image[..., :4], 0.0, 65504.0), dtype=np.float32)


class ThreeDRenderer:
    """Shared-device HDR WebGPU renderer for PBR/VFX material preview."""

    def __init__(self, canvas, gpu_backend) -> None:
        self.canvas = canvas
        self.backend = gpu_backend
        self.device = getattr(gpu_backend, "device", None)
        self.queue = getattr(gpu_backend, "queue", None)
        self.adapter = getattr(gpu_backend, "adapter", None)
        self.available = bool(
            self.device is not None and self.queue is not None and self.adapter is not None and wgpu is not None
        )
        self.error = ""
        self.context = None
        self.surface_format = "bgra8unorm-srgb"
        self._lock = threading.RLock()
        self._shader_module = None
        self._post_shader_module = None
        self._bloom_shader_module = None
        self._pipelines: dict[tuple[str, bool, int], Any] = {}
        self._wireframe_pipelines: dict[int, Any] = {}
        self._pivot_pipelines: dict[tuple[int, int], Any] = {}
        self._shadow_pipelines: dict[bool, Any] = {}
        self._post_pipeline = None
        self._bloom_pipeline = None
        self._uniform_buffer = None
        self._uniform_size = 368
        self._post_uniform_buffer = None
        self._post_uniform_size = 160
        self._bloom_horizontal_uniform_buffer = None
        self._bloom_vertical_uniform_buffer = None
        self._bloom_uniform_size = 32
        self._sampler = None
        self._environment_sampler = None
        self._post_sampler = None
        self._shadow_sampler = None
        self._textures: dict[str, _TextureHandle] = {}
        self._active_material_cache_key: str | None = None
        self._active_channel_tokens: dict[str, str] = {}
        self._material_texture_cache: MemoryLRU[_MaterialTextureSet] = MemoryLRU(512 * 1024 * 1024)
        # Procedural graph meshes can be much more expensive to build and upload
        # than their material maps. Keep recent vertex/index buffer pairs resident
        # and address them by the stable CPU geometry cache key.
        self._geometry_buffer_cache: MemoryLRU[_GeometryBufferSet] = MemoryLRU(256 * 1024 * 1024)
        self._active_geometry_cache_key: str | None = None
        self._environment: _TextureHandle | None = None
        self._environment_name = ""
        self._bind_group = None
        self._bind_group_pipeline = None
        self._shadow_bind_groups: dict[bool, Any] = {}
        self._post_bind_group = None
        self._bloom_horizontal_bind_group = None
        self._bloom_vertical_bind_group = None
        self._mesh_key: tuple[Any, ...] | None = None
        self._mesh: MeshData | None = None
        self._geometry_override: MeshData | None = None
        self._geometry_inspection = False
        self._geometry_override_token = 0
        self._vertex_buffer = None
        self._index_buffer = None
        self._wire_index_buffer = None
        self._wire_index_count = 0
        self._wire_mesh_key: tuple[Any, ...] | None = None
        self._pivot_vertex_buffer = None
        self._pivot_vertex_count = 0
        self._pivot_mesh_key: tuple[Any, ...] | None = None
        self._depth_texture = None
        self._scene_texture = None
        self._msaa_texture = None
        self._bloom_texture_a = None
        self._bloom_texture_b = None
        self._bloom_size = (0, 0)
        self._target_size = (0, 0, 0)
        self._shadow_texture = None
        self._shadow_view = None
        self._msaa_supported = True
        self.material_settings: dict[str, Any] = {}
        self.viewport_settings: dict[str, Any] = viewport_settings()
        self.settings: dict[str, Any] = dict(self.viewport_settings)
        self.connected: frozenset[str] = frozenset()
        self.camera = CameraState()
        if self.available:
            try:
                self._initialize()
            except Exception as exc:
                self.available = False
                self.error = f"{type(exc).__name__}: {exc}"

    def _initialize(self) -> None:
        assert self.device is not None and self.adapter is not None and wgpu is not None
        self.context = self.canvas.get_context("wgpu")
        self.surface_format = self.context.get_preferred_format(self.adapter)
        self.context.configure(
            device=self.device,
            format=self.surface_format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
            alpha_mode="opaque",
        )
        shader_source = files("vfx_texture_lab.shaders").joinpath("preview_3d.wgsl").read_text(encoding="utf-8")
        post_source = files("vfx_texture_lab.shaders").joinpath("preview_3d_post.wgsl").read_text(encoding="utf-8")
        bloom_source = files("vfx_texture_lab.shaders").joinpath("preview_3d_bloom.wgsl").read_text(encoding="utf-8")
        self._shader_module = self.device.create_shader_module(label="VFXTL 3D preview", code=shader_source)
        self._post_shader_module = self.device.create_shader_module(label="VFXTL 3D post", code=post_source)
        self._bloom_shader_module = self.device.create_shader_module(label="VFXTL 3D bloom", code=bloom_source)
        self._uniform_buffer = self.device.create_buffer(
            label="VFXTL 3D uniforms",
            size=self._uniform_size,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._post_uniform_buffer = self.device.create_buffer(
            label="VFXTL 3D post uniforms",
            size=self._post_uniform_size,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._bloom_horizontal_uniform_buffer = self.device.create_buffer(
            label="VFXTL 3D bloom horizontal uniforms",
            size=self._bloom_uniform_size,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._bloom_vertical_uniform_buffer = self.device.create_buffer(
            label="VFXTL 3D bloom vertical uniforms",
            size=self._bloom_uniform_size,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._sampler = self.device.create_sampler(
            label="VFXTL material sampler",
            address_mode_u="repeat",
            address_mode_v="repeat",
            address_mode_w="repeat",
            mag_filter="linear",
            min_filter="linear",
            mipmap_filter="linear",
            max_anisotropy=8,
        )
        self._environment_sampler = self.device.create_sampler(
            label="VFXTL environment sampler",
            address_mode_u="repeat",
            address_mode_v="clamp-to-edge",
            address_mode_w="clamp-to-edge",
            mag_filter="linear",
            min_filter="linear",
            mipmap_filter="linear",
        )
        self._post_sampler = self.device.create_sampler(
            label="VFXTL post sampler",
            address_mode_u="clamp-to-edge",
            address_mode_v="clamp-to-edge",
            mag_filter="linear",
            min_filter="linear",
        )
        self._shadow_sampler = self.device.create_sampler(
            label="VFXTL shadow sampler",
            compare="less-equal",
            address_mode_u="clamp-to-edge",
            address_mode_v="clamp-to-edge",
            mag_filter="linear",
            min_filter="linear",
        )
        self._ensure_shadow_texture()
        self._upload_environment(str(self.viewport_settings["environment_preset"]))
        self.update_material({}, frozenset(), {})
        self.update_viewport(self.viewport_settings)

    def _pipeline(self, surface_mode: str, two_sided: bool, sample_count: int):
        assert self.device is not None and self._shader_module is not None and wgpu is not None
        surface_mode = normalise_surface_mode(surface_mode)
        key = (surface_mode, bool(two_sided), int(sample_count))
        existing = self._pipelines.get(key)
        if existing is not None:
            return existing
        blend = None
        depth_write = True
        if surface_mode == "Alpha Blend":
            blend = {
                "color": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha", "operation": "add"},
                "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha", "operation": "add"},
            }
            depth_write = False
        elif surface_mode == "Premultiplied Alpha":
            blend = {
                "color": {"src_factor": "one", "dst_factor": "one-minus-src-alpha", "operation": "add"},
                "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha", "operation": "add"},
            }
            depth_write = False
        elif surface_mode == "Additive":
            blend = {
                "color": {"src_factor": "src-alpha", "dst_factor": "one", "operation": "add"},
                "alpha": {"src_factor": "one", "dst_factor": "one", "operation": "add"},
            }
            depth_write = False
        pipeline = self.device.create_render_pipeline(
            label=f"VFXTL 3D HDR {surface_mode} {sample_count}x",
            layout="auto",
            vertex={
                "module": self._shader_module,
                "entry_point": "vs_main",
                "buffers": [
                    {
                        "array_stride": 32,
                        "step_mode": "vertex",
                        "attributes": [
                            {"format": "float32x3", "offset": 0, "shader_location": 0},
                            {"format": "float32x3", "offset": 12, "shader_location": 1},
                            {"format": "float32x2", "offset": 24, "shader_location": 2},
                        ],
                    }
                ],
            },
            primitive={
                "topology": "triangle-list",
                "front_face": "ccw",
                "cull_mode": "none" if two_sided else "back",
            },
            depth_stencil={
                "format": "depth24plus",
                "depth_write_enabled": depth_write,
                "depth_compare": "less",
            },
            multisample={"count": sample_count, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": self._shader_module,
                "entry_point": "fs_main",
                "targets": [{"format": SCENE_FORMAT, "blend": blend, "write_mask": wgpu.ColorWrite.ALL}],
            },
        )
        self._pipelines[key] = pipeline
        return pipeline

    def _shadow_pipeline(self, two_sided: bool):
        assert self.device is not None and self._shader_module is not None
        existing = self._shadow_pipelines.get(bool(two_sided))
        if existing is not None:
            return existing
        pipeline = self.device.create_render_pipeline(
            label="VFXTL 3D directional shadow",
            layout="auto",
            vertex={
                "module": self._shader_module,
                "entry_point": "vs_shadow",
                "buffers": [
                    {
                        "array_stride": 32,
                        "step_mode": "vertex",
                        "attributes": [
                            {"format": "float32x3", "offset": 0, "shader_location": 0},
                            {"format": "float32x3", "offset": 12, "shader_location": 1},
                            {"format": "float32x2", "offset": 24, "shader_location": 2},
                        ],
                    }
                ],
            },
            primitive={
                "topology": "triangle-list",
                "front_face": "ccw",
                "cull_mode": "none" if two_sided else "back",
            },
            depth_stencil={
                "format": SHADOW_FORMAT,
                "depth_write_enabled": True,
                "depth_compare": "less",
                "depth_bias": 2,
                "depth_bias_slope_scale": 1.5,
                "depth_bias_clamp": 0.0,
            },
            multisample={"count": 1, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={"module": self._shader_module, "entry_point": "fs_shadow", "targets": []},
        )
        self._shadow_pipelines[bool(two_sided)] = pipeline
        return pipeline

    def _wireframe_pipeline(self, material_pipeline, sample_count: int):
        """Create a line-list overlay pipeline compatible with the active material bindings."""
        assert self.device is not None and self._shader_module is not None and wgpu is not None
        key = id(material_pipeline)
        existing = self._wireframe_pipelines.get(key)
        if existing is not None:
            return existing
        layout = self.device.create_pipeline_layout(
            label="VFXTL 3D wireframe layout",
            bind_group_layouts=[material_pipeline.get_bind_group_layout(0)],
        )
        pipeline = self.device.create_render_pipeline(
            label=f"VFXTL 3D shaded wireframe {sample_count}x",
            layout=layout,
            vertex={
                "module": self._shader_module,
                "entry_point": "vs_wireframe",
                "buffers": [
                    {
                        "array_stride": 32,
                        "step_mode": "vertex",
                        "attributes": [
                            {"format": "float32x3", "offset": 0, "shader_location": 0},
                            {"format": "float32x3", "offset": 12, "shader_location": 1},
                            {"format": "float32x2", "offset": 24, "shader_location": 2},
                        ],
                    }
                ],
            },
            primitive={
                "topology": "line-list",
                "front_face": "ccw",
                "cull_mode": "none",
            },
            # The wireframe vertex shader deliberately shares the shaded
            # surface depth exactly. less-equal admits visible coincident lines
            # while the populated depth buffer rejects hidden/back-side edges.
            depth_stencil={
                "format": "depth24plus",
                "depth_write_enabled": False,
                "depth_compare": "less-equal",
            },
            multisample={"count": sample_count, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": self._shader_module,
                "entry_point": "fs_wireframe",
                "targets": [
                    {
                        "format": SCENE_FORMAT,
                        "blend": {
                            "color": {
                                "src_factor": "src-alpha",
                                "dst_factor": "one-minus-src-alpha",
                                "operation": "add",
                            },
                            "alpha": {
                                "src_factor": "one",
                                "dst_factor": "one-minus-src-alpha",
                                "operation": "add",
                            },
                        },
                        "write_mask": wgpu.ColorWrite.ALL,
                    }
                ],
            },
        )
        self._wireframe_pipelines[key] = pipeline
        return pipeline

    def _ensure_post_pipeline(self):
        assert self.device is not None and self._post_shader_module is not None and wgpu is not None
        if self._post_pipeline is not None:
            return self._post_pipeline
        self._post_pipeline = self.device.create_render_pipeline(
            label="VFXTL 3D tone-map and effects",
            layout="auto",
            vertex={"module": self._post_shader_module, "entry_point": "vs_main", "buffers": []},
            primitive={"topology": "triangle-list", "front_face": "ccw", "cull_mode": "none"},
            multisample={"count": 1, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": self._post_shader_module,
                "entry_point": "fs_main",
                "targets": [{"format": self.surface_format, "blend": None, "write_mask": wgpu.ColorWrite.ALL}],
            },
        )
        return self._post_pipeline

    def _ensure_bloom_pipeline(self):
        assert self.device is not None and self._bloom_shader_module is not None and wgpu is not None
        if self._bloom_pipeline is not None:
            return self._bloom_pipeline
        self._bloom_pipeline = self.device.create_render_pipeline(
            label="VFXTL 3D separable bloom blur",
            layout="auto",
            vertex={"module": self._bloom_shader_module, "entry_point": "vs_main", "buffers": []},
            primitive={"topology": "triangle-list", "front_face": "ccw", "cull_mode": "none"},
            multisample={"count": 1, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": self._bloom_shader_module,
                "entry_point": "fs_main",
                "targets": [{"format": SCENE_FORMAT, "blend": None, "write_mask": wgpu.ColorWrite.ALL}],
            },
        )
        return self._bloom_pipeline

    def _upload_texture(
        self,
        name: str,
        array: np.ndarray,
        texture_store: dict[str, _TextureHandle] | None = None,
        *,
        generate_mips: bool = True,
    ) -> bool:
        assert self.device is not None and self.queue is not None and wgpu is not None
        store = self._textures if texture_store is None else texture_store
        image = _rgba_image(array)
        levels = mip_chain(image) if generate_mips else [image]
        height, width = image.shape[:2]
        mip_count = len(levels)
        old = store.get(name)
        recreated = old is None or (old.width, old.height, old.mip_count) != (width, height, mip_count)
        if recreated:
            if old is not None:
                old.release()
            texture = self.device.create_texture(
                label=f"VFXTL 3D {name} mipmapped",
                size=(width, height, 1),
                mip_level_count=mip_count,
                format="rgba16float",
                usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            )
            old = _TextureHandle(texture, texture.create_view(), width, height, mip_count)
            store[name] = old
        for mip_level, level in enumerate(levels):
            packed = np.ascontiguousarray(np.clip(level, 0.0, 65504.0), dtype=np.float16)
            mip_height, mip_width = packed.shape[:2]
            self.queue.write_texture(
                {"texture": old.texture, "mip_level": mip_level, "origin": (0, 0, 0)},
                packed,
                {"offset": 0, "bytes_per_row": mip_width * 8, "rows_per_image": mip_height},
                (mip_width, mip_height, 1),
            )
        return bool(recreated)

    @staticmethod
    def _texture_set_bytes(textures: dict[str, _TextureHandle]) -> int:
        total = 0
        for handle in textures.values():
            width, height = max(handle.width, 1), max(handle.height, 1)
            for _level in range(max(handle.mip_count, 1)):
                total += width * height * 8  # rgba16float
                width = max((width + 1) // 2, 1)
                height = max((height + 1) // 2, 1)
        return total

    def _upload_environment(self, name: str) -> None:
        assert self.device is not None and self.queue is not None and wgpu is not None
        if self._environment is not None and name == self._environment_name:
            return
        image = load_environment(name)
        rgba = np.concatenate((image, np.ones((*image.shape[:2], 1), dtype=np.float32)), axis=2)
        levels = mip_chain(rgba)
        height, width = rgba.shape[:2]
        if self._environment is not None:
            self._environment.release()
        texture = self.device.create_texture(
            label=f"VFXTL environment {name}",
            size=(width, height, 1),
            mip_level_count=len(levels),
            format="rgba16float",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )
        for mip_level, level in enumerate(levels):
            packed = np.ascontiguousarray(np.clip(level, 0.0, 65504.0), dtype=np.float16)
            mip_height, mip_width = packed.shape[:2]
            self.queue.write_texture(
                {"texture": texture, "mip_level": mip_level, "origin": (0, 0, 0)},
                packed,
                {"offset": 0, "bytes_per_row": mip_width * 8, "rows_per_image": mip_height},
                (mip_width, mip_height, 1),
            )
        self._environment = _TextureHandle(texture, texture.create_view(), width, height, len(levels))
        self._environment_name = name
        self._bind_group = None
        self._bind_group_pipeline = None
        self._post_bind_group = None

    def update_material(
        self,
        textures: dict[str, np.ndarray],
        connected: frozenset[str],
        settings: dict[str, Any],
        *,
        cache_key: str | None = None,
        channel_tokens: dict[str, str] | None = None,
        incremental: bool = False,
    ) -> bool:
        """Upload, incrementally update, or reactivate one material texture set.

        During animation, ``incremental`` keeps the current renderer textures
        alive and uploads only channels whose content token changed. Static maps
        and semantic defaults therefore remain GPU-resident across frames.
        """
        if not self.available:
            return False
        defaults = {
            name: np.asarray(value, dtype=np.float32).reshape(1, 1, 4)
            for name, value in MATERIAL_DEFAULT_VALUES.items()
        }
        desired_tokens = {
            name: str((channel_tokens or {}).get(name) or f"default:{name}")
            for name in MATERIAL_BINDINGS
        }
        reused = False
        with self._lock:
            if incremental:
                # A cached set owns its texture handles. Detach the active entry
                # before mutating it so playback cannot corrupt a reusable cache
                # item or leave active handles vulnerable to LRU eviction.
                if self._active_material_cache_key is not None:
                    active = self._material_texture_cache.take(self._active_material_cache_key)
                    if active is not None:
                        self._textures = active.textures
                        self._active_channel_tokens = dict(active.channel_tokens)
                    self._active_material_cache_key = None

                uploads = 0
                bindings_changed = False
                shadow_bindings_changed = False
                for name in MATERIAL_BINDINGS:
                    token = desired_tokens[name]
                    if name in self._textures and self._active_channel_tokens.get(name) == token:
                        continue
                    recreated = self._upload_texture(
                        name,
                        textures.get(name, defaults[name]),
                        self._textures,
                        generate_mips=not token.startswith("dynamic:"),
                    )
                    bindings_changed = bindings_changed or recreated
                    if recreated and name in {"Base Colour", "Height", "Opacity"}:
                        shadow_bindings_changed = True
                    self._active_channel_tokens[name] = token
                    uploads += 1
                reused = uploads == 0
                self._active_material_cache_key = None
            else:
                cached = self._material_texture_cache.get(cache_key) if cache_key else None
                if cached is not None:
                    self._textures = cached.textures
                    self._active_channel_tokens = dict(cached.channel_tokens)
                    reused = True
                else:
                    # A new keyed result receives its own texture set, allowing
                    # recent static materials to reactivate by swapping views.
                    if self._active_material_cache_key is None:
                        for handle in self._textures.values():
                            handle.release()
                    texture_store: dict[str, _TextureHandle] = {}
                    for name in MATERIAL_BINDINGS:
                        self._upload_texture(name, textures.get(name, defaults[name]), texture_store)
                    self._textures = texture_store
                    self._active_channel_tokens = dict(desired_tokens)
                    if cache_key:
                        self._material_texture_cache.put(
                            cache_key,
                            _MaterialTextureSet(
                                texture_store,
                                self._texture_set_bytes(texture_store),
                                dict(desired_tokens),
                            ),
                        )
                self._active_material_cache_key = cache_key

            self.connected = frozenset(connected)
            self.material_settings = dict(settings)
            self.material_settings["surface_mode"] = normalise_surface_mode(
                self.material_settings.get("surface_mode", "Opaque")
            )
            self.settings = {**self.material_settings, **self.viewport_settings}
            if not incremental or bindings_changed:
                self._bind_group = None
                self._bind_group_pipeline = None
            if not incremental or shadow_bindings_changed:
                self._shadow_bind_groups.clear()
            self._ensure_mesh()
        self.request_draw()
        return reused

    def activate_cached_material(
        self, cache_key: str, connected: frozenset[str], settings: dict[str, Any]
    ) -> bool:
        if not self.available or not cache_key:
            return False
        with self._lock:
            cached = self._material_texture_cache.get(cache_key)
            if cached is None:
                return False
            self._textures = cached.textures
            self._active_channel_tokens = dict(cached.channel_tokens)
            self._active_material_cache_key = cache_key
            self.connected = frozenset(connected)
            self.material_settings = dict(settings)
            self.material_settings["surface_mode"] = normalise_surface_mode(
                self.material_settings.get("surface_mode", "Opaque")
            )
            self.settings = {**self.material_settings, **self.viewport_settings}
            self._bind_group = None
            self._bind_group_pipeline = None
            self._shadow_bind_groups.clear()
            self._ensure_mesh()
        self.request_draw()
        return True

    def set_material_cache_budget_mb(self, budget_mb: int) -> None:
        budget_mb = max(int(budget_mb), 32)
        self._material_texture_cache.set_budget(
            budget_mb * 1024 * 1024,
            protected_key=self._active_material_cache_key,
        )
        # Geometry gets a substantial but bounded share of the renderer budget.
        # One current mesh larger than the budget remains protected by MemoryLRU.
        geometry_cache = getattr(self, "_geometry_buffer_cache", None)
        if geometry_cache is not None:
            geometry_cache.set_budget(
                max(budget_mb // 2, 128) * 1024 * 1024,
                protected_key=getattr(self, "_active_geometry_cache_key", None),
            )

    def material_cache_stats(self) -> CacheStats:
        return self._material_texture_cache.stats()

    def geometry_cache_stats(self) -> CacheStats:
        return self._geometry_buffer_cache.stats()

    def clear_geometry_cache(self) -> None:
        with self._lock:
            # Detach the displayed buffers before clearing the LRU so a manual
            # cache clear cannot invalidate the currently visible mesh mid-frame.
            active = (
                self._geometry_buffer_cache.take(self._active_geometry_cache_key)
                if self._active_geometry_cache_key is not None
                else None
            )
            self._geometry_buffer_cache.clear()
            if active is not None:
                self._vertex_buffer = active.vertex_buffer
                self._index_buffer = active.index_buffer
            self._active_geometry_cache_key = None

    def clear_material_cache(self) -> None:
        with self._lock:
            # Keep the currently displayed set alive as a transient material so
            # clearing caches never leaves the renderer with destroyed bindings
            # between the clear action and the next asynchronous preview.
            active = (
                self._material_texture_cache.take(self._active_material_cache_key)
                if self._active_material_cache_key is not None
                else None
            )
            self._material_texture_cache.clear()
            if active is not None:
                self._textures = active.textures
                self._active_channel_tokens = dict(active.channel_tokens)
            self._active_material_cache_key = None
            self._active_channel_tokens.clear()
            self._bind_group = None
            self._bind_group_pipeline = None
            self._shadow_bind_groups.clear()

    def update_viewport_uniforms(self, settings: dict[str, Any]) -> None:
        """Apply renderer-only values without touching textures, meshes or environments."""
        if not self.available:
            return
        with self._lock:
            self.viewport_settings = viewport_settings(settings)
            self.settings = {**self.material_settings, **self.viewport_settings}
        self.request_draw()

    def update_viewport(self, settings: dict[str, Any]) -> None:
        if not self.available:
            return
        with self._lock:
            previous_mesh_key = self._mesh_key
            previous_environment = str(self.viewport_settings.get("environment_preset", ""))
            previous_aa = str(self.viewport_settings.get("anti_aliasing", ""))
            self.viewport_settings = viewport_settings(settings)
            self.settings = {**self.material_settings, **self.viewport_settings}
            self.camera.projection = str(self.viewport_settings.get("camera_projection", "Perspective"))
            try:
                self._upload_environment(str(self.viewport_settings.get("environment_preset", "Studio Small 02")))
                self._ensure_mesh()
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                return
            if self._mesh_key != previous_mesh_key:
                self._bind_group = None
                self._bind_group_pipeline = None
                self._shadow_bind_groups.clear()
            if previous_environment != str(self.viewport_settings.get("environment_preset")):
                self._bind_group = None
                self._bind_group_pipeline = None
                self._post_bind_group = None
            if previous_aa != str(self.viewport_settings.get("anti_aliasing")):
                self._destroy_render_targets()
            self.error = ""
        self.request_draw()

    @staticmethod
    def _geometry_identity(mesh: MeshData | None) -> tuple[str, object] | None:
        if mesh is None:
            return None
        stable_key = str(getattr(mesh, "cache_key", "") or "")
        return ("cache", stable_key) if stable_key else ("object", id(mesh))

    def set_geometry_override(self, mesh: MeshData | None, *, inspection: bool = False) -> None:
        """Temporarily replace the viewport primitive with graph geometry.

        A persistent geometry result may be wrapped more than once by callers,
        so renderer identity is based on its stable cache key rather than Python
        object identity alone. Unrelated Material edits therefore do not invalidate
        or re-upload an unchanged procedural mesh.
        """
        with self._lock:
            inspection = bool(inspection and mesh is not None)
            if mesh is None and self._geometry_override is None and not self._geometry_inspection:
                return
            previous_identity = self._geometry_identity(self._geometry_override)
            next_identity = self._geometry_identity(mesh)
            if next_identity == previous_identity and inspection == self._geometry_inspection:
                self._geometry_override = mesh
                return
            mesh_changed = next_identity != previous_identity
            self._geometry_override = mesh
            self._geometry_inspection = inspection
            if mesh_changed:
                self._geometry_override_token += 1
                self._mesh_key = None
                if self.available:
                    self._ensure_mesh()
        self.request_draw()

    def clear_geometry_override(self) -> None:
        self.set_geometry_override(None, inspection=False)

    @property
    def has_geometry_override(self) -> bool:
        return self._geometry_override is not None

    def wireframe_enabled(self) -> bool:
        mode = str(self.settings.get("wireframe", "Auto"))
        if mode == "Always":
            return True
        if mode != "Auto" or not self._geometry_inspection:
            return False
        # Building a unique edge list can cost more than drawing the dense mesh
        # itself. Auto mode therefore yields to interactivity for very large
        # procedural meshes; artists can still explicitly select Always.
        return bool(
            self._mesh is None
            or self._mesh.triangle_count <= AUTO_WIREFRAME_TRIANGLE_LIMIT
        )

    @staticmethod
    def _wire_indices(indices: np.ndarray) -> np.ndarray:
        triangles = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
        if triangles.size == 0:
            return np.empty((0,), dtype=np.uint32)
        edges = np.concatenate(
            (triangles[:, (0, 1)], triangles[:, (1, 2)], triangles[:, (2, 0)]),
            axis=0,
        )
        edges.sort(axis=1)
        unique_edges = np.unique(edges, axis=0)
        return np.ascontiguousarray(unique_edges.reshape(-1), dtype=np.uint32)

    def _ensure_wireframe_buffer(self) -> None:
        if not self.available or self._mesh is None or self._mesh_key is None:
            return
        if self._wire_mesh_key == self._mesh_key and self._wire_index_buffer is not None:
            return
        assert self.device is not None and wgpu is not None
        wire_indices = self._wire_indices(self._mesh.indices)
        self._wire_index_count = int(wire_indices.size)
        self._wire_mesh_key = self._mesh_key
        self._wire_index_buffer = None
        if self._wire_index_count:
            self._wire_index_buffer = self.device.create_buffer_with_data(
                label=f"VFXTL {self._mesh.name} wireframe indices",
                data=wire_indices,
                usage=wgpu.BufferUsage.INDEX,
            )

    def _pivot_vertices(self) -> np.ndarray:
        assert self._mesh is not None
        positions = np.asarray(self._mesh.vertices[:, :3], dtype=np.float32)
        if positions.size == 0:
            return np.zeros((0, 6), dtype=np.float32)
        minimum = positions.min(axis=0)
        maximum = positions.max(axis=0)
        extent = maximum - minimum
        size = max(float(extent.max()) * 0.22, 0.08)
        tail = size * 0.25
        colours = {
            "x": (1.0, 0.36, 0.36),
            "y": (0.42, 1.0, 0.48),
            "z": (0.42, 0.65, 1.0),
        }
        vertices = np.asarray([
            (-tail, 0.0, 0.0, *colours["x"]), (size, 0.0, 0.0, *colours["x"]),
            (0.0, -tail, 0.0, *colours["y"]), (0.0, size, 0.0, *colours["y"]),
            (0.0, 0.0, -tail, *colours["z"]), (0.0, 0.0, size, *colours["z"]),
        ], dtype=np.float32)
        return vertices

    def _ensure_pivot_buffer(self) -> None:
        if not self.available or self._mesh is None or self._mesh_key is None:
            return
        if self._pivot_mesh_key == self._mesh_key and self._pivot_vertex_buffer is not None:
            return
        assert self.device is not None and wgpu is not None
        vertices = self._pivot_vertices()
        self._pivot_mesh_key = self._mesh_key
        self._pivot_vertex_count = int(vertices.shape[0])
        self._pivot_vertex_buffer = None
        if self._pivot_vertex_count:
            self._pivot_vertex_buffer = self.device.create_buffer_with_data(
                label=f"VFXTL {self._mesh.name} pivot gizmo",
                data=vertices,
                usage=wgpu.BufferUsage.VERTEX,
            )

    def _pivot_pipeline(self, material_pipeline, sample_count: int):
        assert self.device is not None and self._shader_module is not None and wgpu is not None
        key = (id(material_pipeline), int(sample_count))
        existing = self._pivot_pipelines.get(key)
        if existing is not None:
            return existing
        layout = self.device.create_pipeline_layout(
            label="VFXTL 3D pivot gizmo layout",
            bind_group_layouts=[material_pipeline.get_bind_group_layout(0)],
        )
        pipeline = self.device.create_render_pipeline(
            label=f"VFXTL 3D pivot gizmo {sample_count}x",
            layout=layout,
            vertex={
                "module": self._shader_module,
                "entry_point": "vs_pivot",
                "buffers": [
                    {
                        "array_stride": 24,
                        "step_mode": "vertex",
                        "attributes": [
                            {"format": "float32x3", "offset": 0, "shader_location": 0},
                            {"format": "float32x3", "offset": 12, "shader_location": 1},
                        ],
                    }
                ],
            },
            primitive={
                "topology": "line-list",
                "front_face": "ccw",
                "cull_mode": "none",
            },
            depth_stencil={
                "format": "depth24plus",
                "depth_write_enabled": False,
                "depth_compare": "always",
            },
            multisample={"count": sample_count, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": self._shader_module,
                "entry_point": "fs_pivot",
                "targets": [
                    {
                        "format": SCENE_FORMAT,
                        "blend": {
                            "color": {
                                "src_factor": "src-alpha",
                                "dst_factor": "one-minus-src-alpha",
                                "operation": "add",
                            },
                            "alpha": {
                                "src_factor": "one",
                                "dst_factor": "one-minus-src-alpha",
                                "operation": "add",
                            },
                        },
                        "write_mask": wgpu.ColorWrite.ALL,
                    }
                ],
            },
        )
        self._pivot_pipelines[key] = pipeline
        return pipeline

    @staticmethod
    def _destroy_buffer(buffer: Any) -> None:
        destroy = getattr(buffer, "destroy", None)
        if callable(destroy):
            try:
                destroy()
            except Exception:
                pass

    def _release_transient_mesh_buffers(self) -> None:
        # Cached graph buffers are owned by _geometry_buffer_cache. Built-in and
        # detached active buffers are renderer-owned transients.
        if self._active_geometry_cache_key is not None:
            return
        self._destroy_buffer(self._vertex_buffer)
        self._destroy_buffer(self._index_buffer)

    def _activate_geometry_buffers(self, cache_key: str, mesh: MeshData) -> bool:
        cached = self._geometry_buffer_cache.get(cache_key)
        if cached is None:
            return False
        self._release_transient_mesh_buffers()
        self._vertex_buffer = cached.vertex_buffer
        self._index_buffer = cached.index_buffer
        self._active_geometry_cache_key = cache_key
        return True

    def _create_geometry_buffers(self, mesh: MeshData, cache_key: str | None = None) -> None:
        assert self.device is not None and wgpu is not None
        vertex_buffer = self.device.create_buffer_with_data(
            label=f"VFXTL {mesh.name} vertices", data=mesh.vertices, usage=wgpu.BufferUsage.VERTEX
        )
        index_buffer = self.device.create_buffer_with_data(
            label=f"VFXTL {mesh.name} indices", data=mesh.indices, usage=wgpu.BufferUsage.INDEX
        )
        self._release_transient_mesh_buffers()
        if cache_key:
            buffer_set = _GeometryBufferSet(
                vertex_buffer,
                index_buffer,
                int(mesh.vertices.nbytes) + int(mesh.indices.nbytes),
            )
            self._geometry_buffer_cache.put(cache_key, buffer_set)
            self._active_geometry_cache_key = cache_key
        else:
            self._active_geometry_cache_key = None
        self._vertex_buffer = vertex_buffer
        self._index_buffer = index_buffer

    def _ensure_mesh(self) -> None:
        if not self.available:
            return
        assert self.device is not None and wgpu is not None
        geometry_cache_key: str | None = None
        if self._geometry_override is not None:
            mesh = self._geometry_override
            geometry_cache_key = str(getattr(mesh, "cache_key", "") or "") or None
            key = (
                "graph-geometry",
                geometry_cache_key if geometry_cache_key is not None else self._geometry_override_token,
                mesh.vertex_count,
                mesh.triangle_count,
            )
        else:
            mesh_name = str(self.settings.get("preview_mesh", "Terrain Plane"))
            quality = str(self.settings.get("mesh_quality", "High"))
            custom_path = str(self.settings.get("custom_mesh", ""))
            if mesh_name == "Custom Mesh" and not custom_path:
                return
            reload_token = self.settings.get("_reload_token", 0)
            key = (mesh_name, quality, custom_path, reload_token)
            if key == self._mesh_key and self._mesh is not None:
                return
            mesh = mesh_for_settings(mesh_name, quality, custom_path)
        if key == self._mesh_key and self._mesh is not None:
            return
        self._mesh = mesh
        self._mesh_key = key
        if geometry_cache_key and self._activate_geometry_buffers(geometry_cache_key, mesh):
            pass
        else:
            self._create_geometry_buffers(mesh, geometry_cache_key)
        self._wire_mesh_key = None
        self._wire_index_buffer = None
        self._wire_index_count = 0
        self._pivot_mesh_key = None
        self._pivot_vertex_buffer = None
        self._pivot_vertex_count = 0

    def _destroy_render_targets(self) -> None:
        for texture in (
            self._depth_texture, self._scene_texture, self._msaa_texture,
            self._bloom_texture_a, self._bloom_texture_b,
        ):
            if texture is not None:
                try:
                    texture.destroy()
                except Exception:
                    pass
        self._depth_texture = self._scene_texture = self._msaa_texture = None
        self._bloom_texture_a = self._bloom_texture_b = None
        self._bloom_size = (0, 0)
        self._target_size = (0, 0, 0)
        self._post_bind_group = None
        self._bloom_horizontal_bind_group = None
        self._bloom_vertical_bind_group = None

    def _ensure_render_targets(self, width: int, height: int, sample_count: int) -> None:
        assert self.device is not None and wgpu is not None
        key = (width, height, sample_count)
        if self._target_size == key and self._scene_texture is not None and self._depth_texture is not None:
            return
        self._destroy_render_targets()
        self._scene_texture = self.device.create_texture(
            label="VFXTL 3D HDR scene",
            size=(width, height, 1),
            format=SCENE_FORMAT,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING,
        )
        if sample_count > 1:
            self._msaa_texture = self.device.create_texture(
                label=f"VFXTL 3D {sample_count}x MSAA",
                size=(width, height, 1),
                sample_count=sample_count,
                format=SCENE_FORMAT,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
            )
        self._depth_texture = self.device.create_texture(
            label="VFXTL 3D depth",
            size=(width, height, 1),
            sample_count=sample_count,
            format="depth24plus",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
        )
        bloom_width = max((width + 1) // 2, 1)
        bloom_height = max((height + 1) // 2, 1)
        bloom_usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING
        self._bloom_texture_a = self.device.create_texture(
            label="VFXTL 3D bloom horizontal", size=(bloom_width, bloom_height, 1),
            format=SCENE_FORMAT, usage=bloom_usage,
        )
        self._bloom_texture_b = self.device.create_texture(
            label="VFXTL 3D bloom vertical", size=(bloom_width, bloom_height, 1),
            format=SCENE_FORMAT, usage=bloom_usage,
        )
        self._bloom_size = (bloom_width, bloom_height)
        self._target_size = key
        self._post_bind_group = None
        self._bloom_horizontal_bind_group = None
        self._bloom_vertical_bind_group = None

    def _ensure_shadow_texture(self) -> None:
        assert self.device is not None and wgpu is not None
        if self._shadow_texture is not None:
            return
        self._shadow_texture = self.device.create_texture(
            label="VFXTL directional shadow map",
            size=(SHADOW_SIZE, SHADOW_SIZE, 1),
            format=SHADOW_FORMAT,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING,
        )
        self._shadow_view = self._shadow_texture.create_view()
        self._bind_group = None

    def _matrix_state(self, width: int, height: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        settings = self.settings
        eye = self.camera.eye()
        target = self.camera.target
        view = _look_at(eye, target, np.array((0.0, 1.0, 0.0), dtype=np.float32))
        aspect = width / max(height, 1)
        if self.camera.projection == "Orthographic":
            projection = _orthographic(self.camera.distance * 0.55, aspect)
        else:
            fov = min(max(float(settings.get("camera_fov", 48.0)), 15.0), 100.0)
            projection = _perspective(math.radians(fov), aspect)
        view_proj = projection @ view
        inverse_view_proj = np.linalg.inv(view_proj).astype(np.float32)

        azimuth = math.radians(float(settings.get("sun_azimuth", 135.0)))
        elevation = math.radians(float(settings.get("sun_elevation", 42.0)))
        light_direction = np.array(
            (
                math.cos(elevation) * math.sin(azimuth),
                -math.sin(elevation),
                math.cos(elevation) * math.cos(azimuth),
                0.0,
            ),
            dtype=np.float32,
        )
        light_target = np.array((0.0, 0.0, 0.0), dtype=np.float32)
        light_eye = light_target - light_direction[:3] * 10.0
        light_view = _look_at(light_eye, light_target, np.array((0.0, 1.0, 0.0), dtype=np.float32))
        tile_count = (
            3
            if str(settings.get("tile_preview", "1 × 1")) == "3 × 3"
            and self._geometry_override is None
            and str(settings.get("preview_mesh", "Terrain Plane")) == "Terrain Plane"
            else 1
        )
        light_projection = _orthographic(4.8 if tile_count == 3 else 2.8, 1.0, -30.0, 30.0)
        light_view_proj = light_projection @ light_view
        return view_proj, inverse_view_proj, eye, light_direction, light_view_proj

    def _uniform_data(self, width: int, height: int) -> np.ndarray:
        settings = self.settings
        view_proj, _inverse, eye, light_direction, light_view_proj = self._matrix_state(width, height)
        model = np.eye(4, dtype=np.float32)
        surface_mode = {
            "Opaque": 0.0,
            "Alpha Cutout": 1.0,
            "Alpha Blend": 2.0,
            "Premultiplied Alpha": 3.0,
            "Additive": 4.0,
        }.get(normalise_surface_mode(settings.get("surface_mode", "Opaque")), 0.0)
        normal_y = -1.0 if str(settings.get("normal_y", "OpenGL (+Y)")) == "DirectX (-Y)" else 1.0
        tile_count = (
            3.0
            if str(settings.get("tile_preview", "1 × 1")) == "3 × 3"
            and self._geometry_override is None
            and str(settings.get("preview_mesh", "Terrain Plane")) == "Terrain Plane"
            else 1.0
        )
        height_image = self._textures.get("Height")
        texel_x = 1.0 / max(height_image.width if height_image else 1, 1)
        texel_y = 1.0 / max(height_image.height if height_image else 1, 1)
        mesh_name = str(settings.get("preview_mesh", "Terrain Plane"))
        mesh_is_plane = self._geometry_override is None and mesh_name in ("Terrain Plane", "Flat Plane")
        debug_view = {
            "Final Material": 0.0,
            "Base Colour": 1.0,
            "Surface Normals (World)": 2.0,
            "Normal Map (Tangent)": 11.0,
            "Height": 3.0,
            "Roughness": 4.0,
            "Metallic": 5.0,
            "Ambient Occlusion": 6.0,
            "Emissive": 7.0,
            "Opacity": 8.0,
            "UV Checker": 9.0,
            "Mesh Normals": 10.0,
        }.get(str(settings.get("debug_view", "Final Material")), 0.0)
        environment_mips = float(self._environment.mip_count if self._environment else 1)
        blocks = [
            _matrix_bytes(view_proj),
            _matrix_bytes(model),
            _matrix_bytes(light_view_proj),
            np.array((*eye, 1.0), dtype=np.float32),
            light_direction,
            np.array(
                (
                    float(settings.get("displacement_amount", 0.25)),
                    float(settings.get("height_midpoint", 0.5)),
                    float(settings.get("normal_strength", 1.0)),
                    1.0 if bool(settings.get("invert_height", False)) else 0.0,
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    float(settings.get("emissive_intensity", 1.0)),
                    float(settings.get("cutout_threshold", 0.5)),
                    normal_y,
                    surface_mode,
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    float(settings.get("environment_intensity", 1.0)),
                    float(settings.get("sun_intensity", 2.5)),
                    float(settings.get("background_brightness", 1.0)),
                    tile_count,
                ),
                dtype=np.float32,
            ),
            np.array(
                (texel_x, texel_y, 1.0 if bool(settings.get("derive_normals", True)) else 0.0, 1.0 if "Normal" in self.connected else 0.0),
                dtype=np.float32,
            ),
            np.array(
                (
                    1.0 if "Ambient Occlusion" in self.connected else 0.0,
                    1.0 if "Metallic" in self.connected else 0.0,
                    1.0 if "Roughness" in self.connected else 0.0,
                    1.0 if "Specular Level" in self.connected else 0.0,
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    1.0 if "Height" in self.connected else 0.0,
                    1.0 if "Opacity" in self.connected else 0.0,
                    1.0 if bool(settings.get("show_grid", False)) else 0.0,
                    1.0 if mesh_is_plane else 0.0,
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    debug_view,
                    1.0 if bool(settings.get("show_uv_grid", False)) else 0.0,
                    1.0 if str(settings.get("lighting_mode", "Lit")) == "Unlit" else 0.0,
                    math.radians(float(settings.get("environment_rotation", 0.0))),
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    environment_mips,
                    1.0 if bool(settings.get("shadows", True)) else 0.0,
                    float(settings.get("shadow_strength", 0.7)),
                    1.0 / SHADOW_SIZE,
                ),
                dtype=np.float32,
            ),
            np.array(
                (float(settings.get("material_tiling", 1.0)), 0.0, 0.0, 0.0),
                dtype=np.float32,
            ),
        ]
        data = np.concatenate(blocks).astype(np.float32)
        if data.size != 92:
            raise RuntimeError(f"3D uniform packing error: expected 92 floats, got {data.size}")
        return data

    def _post_uniform_data(self, width: int, height: int) -> np.ndarray:
        settings = self.settings
        _view_proj, inverse_view_proj, eye, _light, _light_view_proj = self._matrix_state(width, height)
        background = _parse_colour(str(settings.get("background", "#2a3038ff")), (0.16, 0.19, 0.22, 1.0))
        background_linear = tuple(_srgb_to_linear(component) for component in background[:3])
        tone_mode = {"ACES": 0.0, "Neutral": 1.0, "Reinhard": 2.0, "Linear": 3.0}.get(
            str(settings.get("tone_mapping", "ACES")), 0.0
        )
        blocks = [
            _matrix_bytes(inverse_view_proj),
            np.array((*eye, 1.0), dtype=np.float32),
            np.array((*background_linear, float(settings.get("background_brightness", 1.0))), dtype=np.float32),
            np.array(
                (
                    float(settings.get("exposure", 0.0)),
                    tone_mode,
                    1.0 if bool(settings.get("bloom", True)) else 0.0,
                    float(settings.get("bloom_intensity", 0.35)),
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    float(settings.get("bloom_threshold", 1.0)),
                    float(settings.get("bloom_radius", 4.0)),
                    1.0 if bool(settings.get("sharpen", False)) else 0.0,
                    float(settings.get("sharpen_strength", 0.18)),
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    1.0 if bool(settings.get("vignette", False)) else 0.0,
                    float(settings.get("vignette_strength", 0.22)),
                    1.0 if bool(settings.get("show_environment", True)) else 0.0,
                    math.radians(float(settings.get("environment_rotation", 0.0))),
                ),
                dtype=np.float32,
            ),
            np.array(
                (
                    1.0 / max(width, 1),
                    1.0 / max(height, 1),
                    1.0 if self.camera.projection == "Perspective" else 0.0,
                    float(self._environment.mip_count if self._environment else 1),
                ),
                dtype=np.float32,
            ),
        ]
        data = np.concatenate(blocks).astype(np.float32)
        if data.size != 40:
            raise RuntimeError(f"3D post uniform packing error: expected 40 floats, got {data.size}")
        return data

    def _bloom_uniform_data(self, input_width: int, input_height: int, direction_x: float, direction_y: float, *, prefilter: bool) -> np.ndarray:
        radius = max(float(self.settings.get("bloom_radius", 4.0)), 1.0)
        radius_scale = radius / (4.0 if prefilter else 8.0)
        return np.array((
            1.0 / max(int(input_width), 1), 1.0 / max(int(input_height), 1),
            float(direction_x), float(direction_y),
            float(self.settings.get("bloom_threshold", 1.0)), max(radius_scale, 0.125),
            1.0 if prefilter else 0.0, 0.0,
        ), dtype=np.float32)

    def _create_bind_group(self, pipeline) -> Any:
        assert (
            self.device is not None
            and self._uniform_buffer is not None
            and self._sampler is not None
            and self._environment is not None
            and self._environment_sampler is not None
            and self._shadow_view is not None
            and self._shadow_sampler is not None
        )
        entries: list[dict[str, Any]] = [
            {"binding": 0, "resource": {"buffer": self._uniform_buffer, "offset": 0, "size": self._uniform_size}}
        ]
        for binding, name in enumerate(MATERIAL_BINDINGS, start=1):
            entries.append({"binding": binding, "resource": self._textures[name].view})
        entries.extend(
            (
                {"binding": 10, "resource": self._sampler},
                {"binding": 11, "resource": self._environment.view},
                {"binding": 12, "resource": self._environment_sampler},
                {"binding": 13, "resource": self._shadow_view},
                {"binding": 14, "resource": self._shadow_sampler},
            )
        )
        return self.device.create_bind_group(
            label="VFXTL 3D HDR material bindings", layout=pipeline.get_bind_group_layout(0), entries=entries
        )

    def _create_shadow_bind_group(self, pipeline) -> Any:
        assert self.device is not None and self._uniform_buffer is not None and self._sampler is not None
        return self.device.create_bind_group(
            label="VFXTL 3D shadow bindings",
            layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._uniform_buffer, "offset": 0, "size": self._uniform_size}},
                {"binding": 1, "resource": self._textures["Base Colour"].view},
                {"binding": 4, "resource": self._textures["Height"].view},
                {"binding": 9, "resource": self._textures["Opacity"].view},
                {"binding": 10, "resource": self._sampler},
            ],
        )

    def _create_bloom_bind_group(self, pipeline, uniform_buffer, input_texture, label: str) -> Any:
        assert self.device is not None and self._post_sampler is not None
        return self.device.create_bind_group(
            label=label, layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": uniform_buffer, "offset": 0, "size": self._bloom_uniform_size}},
                {"binding": 1, "resource": input_texture.create_view()},
                {"binding": 2, "resource": self._post_sampler},
            ],
        )

    def _create_post_bind_group(self, pipeline) -> Any:
        assert (self.device is not None and self._post_uniform_buffer is not None
            and self._scene_texture is not None and self._bloom_texture_b is not None
            and self._post_sampler is not None and self._environment is not None
            and self._environment_sampler is not None)
        return self.device.create_bind_group(
            label="VFXTL 3D post bindings", layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._post_uniform_buffer, "offset": 0, "size": self._post_uniform_size}},
                {"binding": 1, "resource": self._scene_texture.create_view()},
                {"binding": 2, "resource": self._post_sampler},
                {"binding": 3, "resource": self._environment.view},
                {"binding": 4, "resource": self._environment_sampler},
                {"binding": 5, "resource": self._bloom_texture_b.create_view()},
            ],
        )

    def request_draw(self) -> None:
        if self.available:
            self.canvas.request_draw()

    def _draw_impl(self, sample_count: int) -> None:
        assert self.device is not None and self.queue is not None and wgpu is not None and self.context is not None
        self._ensure_mesh()
        if self._mesh is None or self._vertex_buffer is None or self._index_buffer is None:
            return
        width, height = self.canvas.get_physical_size()
        width = max(int(width), 1)
        height = max(int(height), 1)
        self._ensure_render_targets(width, height, sample_count)
        self._ensure_shadow_texture()
        surface_mode = normalise_surface_mode(self.settings.get("surface_mode", "Opaque"))
        two_sided = bool(self.settings.get("two_sided", False))
        pipeline = self._pipeline(surface_mode, two_sided, sample_count)
        wireframe_pipeline = None
        if self.wireframe_enabled():
            self._ensure_wireframe_buffer()
            if self._wire_index_buffer is not None and self._wire_index_count > 0:
                wireframe_pipeline = self._wireframe_pipeline(pipeline, sample_count)
        pivot_pipeline = None
        if self._geometry_inspection:
            self._ensure_pivot_buffer()
            if self._pivot_vertex_buffer is not None and self._pivot_vertex_count > 0:
                pivot_pipeline = self._pivot_pipeline(pipeline, sample_count)
        shadow_pipeline = self._shadow_pipeline(two_sided)
        bloom_pipeline = self._ensure_bloom_pipeline()
        post_pipeline = self._ensure_post_pipeline()
        if self._bind_group is None or self._bind_group_pipeline is not pipeline:
            self._bind_group = self._create_bind_group(pipeline)
            self._bind_group_pipeline = pipeline
        shadow_bind_group = self._shadow_bind_groups.get(two_sided)
        if shadow_bind_group is None:
            shadow_bind_group = self._create_shadow_bind_group(shadow_pipeline)
            self._shadow_bind_groups[two_sided] = shadow_bind_group
        assert (self._scene_texture is not None and self._bloom_texture_a is not None
            and self._bloom_texture_b is not None and self._bloom_horizontal_uniform_buffer is not None
            and self._bloom_vertical_uniform_buffer is not None)
        if self._bloom_horizontal_bind_group is None:
            self._bloom_horizontal_bind_group = self._create_bloom_bind_group(
                bloom_pipeline, self._bloom_horizontal_uniform_buffer, self._scene_texture,
                "VFXTL 3D bloom horizontal bindings")
        if self._bloom_vertical_bind_group is None:
            self._bloom_vertical_bind_group = self._create_bloom_bind_group(
                bloom_pipeline, self._bloom_vertical_uniform_buffer, self._bloom_texture_a,
                "VFXTL 3D bloom vertical bindings")
        if self._post_bind_group is None:
            self._post_bind_group = self._create_post_bind_group(post_pipeline)

        bloom_width, bloom_height = self._bloom_size
        self.queue.write_buffer(self._uniform_buffer, 0, self._uniform_data(width, height))
        self.queue.write_buffer(self._post_uniform_buffer, 0, self._post_uniform_data(width, height))
        self.queue.write_buffer(self._bloom_horizontal_uniform_buffer, 0,
            self._bloom_uniform_data(width, height, 1.0, 0.0, prefilter=True))
        self.queue.write_buffer(self._bloom_vertical_uniform_buffer, 0,
            self._bloom_uniform_data(bloom_width, bloom_height, 0.0, 1.0, prefilter=False))
        instance_count = (
            9
            if str(self.settings.get("tile_preview", "1 × 1")) == "3 × 3"
            and str(self.settings.get("preview_mesh", "Terrain Plane")) == "Terrain Plane"
            else 1
        )
        encoder = self.device.create_command_encoder(label="VFXTL 3D HDR preview command")

        if bool(self.settings.get("shadows", True)) and float(self.settings.get("sun_intensity", 2.5)) > 0.0:
            shadow_pass = encoder.begin_render_pass(
                label="VFXTL directional shadow pass",
                color_attachments=[],
                depth_stencil_attachment={
                    "view": self._shadow_view,
                    "depth_clear_value": 1.0,
                    "depth_load_op": "clear",
                    "depth_store_op": "store",
                    "stencil_read_only": True,
                },
            )
            shadow_pass.set_pipeline(shadow_pipeline)
            shadow_pass.set_bind_group(0, shadow_bind_group)
            shadow_pass.set_vertex_buffer(0, self._vertex_buffer)
            shadow_pass.set_index_buffer(self._index_buffer, "uint32")
            shadow_pass.draw_indexed(int(self._mesh.indices.size), instance_count)
            shadow_pass.end()

        assert self._scene_texture is not None and self._depth_texture is not None
        scene_view = self._scene_texture.create_view()
        colour_view = self._msaa_texture.create_view() if self._msaa_texture is not None else scene_view
        scene_pass = encoder.begin_render_pass(
            label="VFXTL HDR material pass",
            color_attachments=[
                {
                    "view": colour_view,
                    "resolve_target": scene_view if self._msaa_texture is not None else None,
                    "clear_value": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
                    "load_op": "clear",
                    "store_op": "store",
                }
            ],
            depth_stencil_attachment={
                "view": self._depth_texture.create_view(),
                "depth_clear_value": 1.0,
                "depth_load_op": "clear",
                "depth_store_op": "store",
                "stencil_read_only": True,
            },
        )
        scene_pass.set_pipeline(pipeline)
        scene_pass.set_bind_group(0, self._bind_group)
        scene_pass.set_vertex_buffer(0, self._vertex_buffer)
        scene_pass.set_index_buffer(self._index_buffer, "uint32")
        scene_pass.draw_indexed(int(self._mesh.indices.size), instance_count)
        if wireframe_pipeline is not None and self._wire_index_buffer is not None:
            scene_pass.set_pipeline(wireframe_pipeline)
            scene_pass.set_bind_group(0, self._bind_group)
            scene_pass.set_vertex_buffer(0, self._vertex_buffer)
            scene_pass.set_index_buffer(self._wire_index_buffer, "uint32")
            scene_pass.draw_indexed(self._wire_index_count, instance_count)
        if pivot_pipeline is not None and self._pivot_vertex_buffer is not None:
            scene_pass.set_pipeline(pivot_pipeline)
            scene_pass.set_bind_group(0, self._bind_group)
            scene_pass.set_vertex_buffer(0, self._pivot_vertex_buffer)
            scene_pass.draw(self._pivot_vertex_count)
        scene_pass.end()

        if bool(self.settings.get("bloom", True)):
            bloom_horizontal_pass = encoder.begin_render_pass(
                label="VFXTL bloom prefilter and horizontal blur",
                color_attachments=[{"view": self._bloom_texture_a.create_view(), "resolve_target": None,
                    "clear_value": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0}, "load_op": "clear", "store_op": "store"}],)
            bloom_horizontal_pass.set_pipeline(bloom_pipeline)
            bloom_horizontal_pass.set_bind_group(0, self._bloom_horizontal_bind_group)
            bloom_horizontal_pass.draw(3)
            bloom_horizontal_pass.end()
            bloom_vertical_pass = encoder.begin_render_pass(
                label="VFXTL bloom vertical blur",
                color_attachments=[{"view": self._bloom_texture_b.create_view(), "resolve_target": None,
                    "clear_value": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0}, "load_op": "clear", "store_op": "store"}],)
            bloom_vertical_pass.set_pipeline(bloom_pipeline)
            bloom_vertical_pass.set_bind_group(0, self._bloom_vertical_bind_group)
            bloom_vertical_pass.draw(3)
            bloom_vertical_pass.end()

        target_view = self.context.get_current_texture().create_view()
        post_pass = encoder.begin_render_pass(
            label="VFXTL tone-map, bloom and display pass",
            color_attachments=[
                {
                    "view": target_view,
                    "resolve_target": None,
                    "clear_value": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0},
                    "load_op": "clear",
                    "store_op": "store",
                }
            ],
        )
        post_pass.set_pipeline(post_pipeline)
        post_pass.set_bind_group(0, self._post_bind_group)
        post_pass.draw(3)
        post_pass.end()
        self.queue.submit([encoder.finish()])

    def draw(self) -> None:
        if not self.available or self.context is None:
            return
        with self._lock:
            requested = 4 if str(self.settings.get("anti_aliasing", "4× MSAA")) == "4× MSAA" else 1
            sample_count = requested if self._msaa_supported else 1
            try:
                self._draw_impl(sample_count)
                self.error = ""
            except Exception as exc:
                if sample_count > 1:
                    # Some low-end adapters expose WebGPU but cannot multisample
                    # rgba16float. Fall back cleanly without losing the preview.
                    self._msaa_supported = False
                    self._destroy_render_targets()
                    self._pipelines = {key: value for key, value in self._pipelines.items() if key[2] == 1}
                    self._wireframe_pipelines.clear()
                    self._pivot_pipelines.clear()
                    try:
                        self._draw_impl(1)
                        self.error = "4× MSAA is unavailable on this adapter; using single-sample HDR rendering."
                        return
                    except Exception as fallback_exc:
                        exc = fallback_exc
                self.error = f"{type(exc).__name__}: {exc}"
                raise

    def orbit(self, delta_x: float, delta_y: float) -> None:
        self.camera.yaw -= float(delta_x) * 0.008
        self.camera.pitch = min(
            max(self.camera.pitch - float(delta_y) * 0.008, math.radians(-88.0)), math.radians(88.0)
        )
        self.request_draw()

    def dolly(self, wheel_delta: float) -> None:
        self.camera.distance = min(max(self.camera.distance * math.exp(-float(wheel_delta) * 0.0012), 0.35), 30.0)
        self.request_draw()

    def pan(self, delta_x: float, delta_y: float) -> None:
        eye = self.camera.eye()
        forward = _normalise(self.camera.target - eye)
        right = _normalise(np.cross(forward, np.array((0.0, 1.0, 0.0), dtype=np.float32)))
        up = _normalise(np.cross(right, forward))
        scale = self.camera.distance * 0.0016
        target = self.camera.target + (-right * float(delta_x) + up * float(delta_y)) * scale
        self.camera.target_x, self.camera.target_y, self.camera.target_z = map(float, target)
        self.request_draw()

    def reset_camera(self) -> None:
        projection = self.camera.projection
        self.camera = CameraState(projection=projection)
        self.request_draw()

    def set_view(self, view: str) -> None:
        self.camera.target_x = self.camera.target_y = self.camera.target_z = 0.0
        self.camera.distance = 3.2
        if view == "Top":
            self.camera.yaw = 0.0
            self.camera.pitch = math.radians(89.0)
        elif view == "Front":
            self.camera.yaw = math.radians(180.0)
            self.camera.pitch = 0.0
        elif view == "Back":
            self.camera.yaw = 0.0
            self.camera.pitch = 0.0
        elif view in ("Side", "Right"):
            self.camera.yaw = math.radians(90.0)
            self.camera.pitch = 0.0
        elif view == "Left":
            self.camera.yaw = math.radians(-90.0)
            self.camera.pitch = 0.0
        elif view == "Bottom":
            self.camera.yaw = 0.0
            self.camera.pitch = math.radians(-89.0)
        else:
            self.camera.yaw = math.radians(42.0)
            self.camera.pitch = math.radians(34.0)
        self.request_draw()

    def rotate_degrees(self, degrees: float) -> None:
        self.camera.yaw = (self.camera.yaw + math.radians(float(degrees))) % math.tau
        self.request_draw()

    def camera_state(self) -> dict[str, float | str]:
        return {
            "yaw": float(self.camera.yaw),
            "pitch": float(self.camera.pitch),
            "distance": float(self.camera.distance),
            "target_x": float(self.camera.target_x),
            "target_y": float(self.camera.target_y),
            "target_z": float(self.camera.target_z),
            "projection": str(self.camera.projection),
        }

    def restore_camera_state(self, values: dict[str, Any]) -> None:
        try:
            self.camera.yaw = float(values.get("yaw", self.camera.yaw))
            self.camera.pitch = min(max(float(values.get("pitch", self.camera.pitch)), math.radians(-88.0)), math.radians(88.0))
            self.camera.distance = min(max(float(values.get("distance", self.camera.distance)), 0.35), 30.0)
            self.camera.target_x = float(values.get("target_x", self.camera.target_x))
            self.camera.target_y = float(values.get("target_y", self.camera.target_y))
            self.camera.target_z = float(values.get("target_z", self.camera.target_z))
        except (TypeError, ValueError):
            return
        self.request_draw()

    @property
    def mesh_summary(self) -> str:
        if self._mesh is None:
            return "No mesh"
        summary = (
            f"{self._mesh.name} · {self._mesh.vertex_count:,} vertices · "
            f"{self._mesh.triangle_count:,} triangles"
        )
        if (
            self._geometry_inspection
            and str(self.settings.get("wireframe", "Auto")) == "Auto"
            and self._mesh.triangle_count > AUTO_WIREFRAME_TRIANGLE_LIMIT
        ):
            summary += " · Auto wireframe hidden for dense preview"
        return summary

    def release(self) -> None:
        if self._active_material_cache_key is None:
            for texture in self._textures.values():
                texture.release()
        self._textures.clear()
        self._material_texture_cache.clear()
        self._active_material_cache_key = None
        if self._active_geometry_cache_key is None:
            self._destroy_buffer(self._vertex_buffer)
            self._destroy_buffer(self._index_buffer)
        self._vertex_buffer = None
        self._index_buffer = None
        self._geometry_buffer_cache.clear()
        self._active_geometry_cache_key = None
        if self._environment is not None:
            self._environment.release()
            self._environment = None
        self._destroy_render_targets()
        if self._shadow_texture is not None:
            try:
                self._shadow_texture.destroy()
            except Exception:
                pass
        self._shadow_texture = self._shadow_view = None
