"""Reusable persistence for expensive manual geometry operations.

Manual geometry nodes publish a completed mesh transactionally and keep using it
while artists adjust the settings for a future run.  The payload is compressed
into the graph so it survives save/reopen, while a bounded decode cache avoids
inflating the same mesh for every preview refresh.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, Mapping

import base64
import hashlib
import json
import threading

import numpy as np

from .geometry import GeometryData, GeometryEvalContext, GeometryEvaluationCancelled


@dataclass(slots=True)
class ManualGeometryResult:
    geometry: GeometryData
    diagnostics: dict[str, Any]

    @property
    def memory_bytes(self) -> int:
        return int(self.geometry.vertices.nbytes + self.geometry.indices.nbytes)


_RESULT_CACHE: "OrderedDict[str, ManualGeometryResult]" = OrderedDict()
_RESULT_CACHE_LOCK = threading.RLock()
_RESULT_CACHE_BUDGET = 768 * 1024 * 1024


def geometry_operation_signature(
    geometry: GeometryData,
    parameters: Mapping[str, Any],
    parameter_names: tuple[str, ...],
    *,
    include_normals: bool = True,
    include_uvs: bool = True,
) -> str:
    """Hash the source mesh and operation settings in a deterministic form."""

    digest = hashlib.blake2b(digest_size=20)
    attribute_count = 8 if include_uvs else (6 if include_normals else 3)
    digest.update(
        np.ascontiguousarray(
            geometry.vertices[:, :attribute_count], dtype=np.float32
        ).tobytes()
    )
    digest.update(np.ascontiguousarray(geometry.indices, dtype=np.uint32).tobytes())
    digest.update(geometry.uv_origin.encode("ascii"))
    relevant = {name: parameters.get(name) for name in parameter_names}
    digest.update(
        json.dumps(
            relevant, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    )
    return digest.hexdigest()


def encode_manual_geometry_result(result: ManualGeometryResult) -> str:
    stream = BytesIO()
    np.savez_compressed(
        stream,
        vertices=np.asarray(result.geometry.vertices, dtype=np.float32),
        indices=np.asarray(result.geometry.indices, dtype=np.uint32),
        name=np.asarray([result.geometry.name]),
        uv_origin=np.asarray([result.geometry.uv_origin]),
        diagnostics=np.asarray(
            [json.dumps(result.diagnostics, separators=(",", ":"), default=str)]
        ),
    )
    return base64.b64encode(stream.getvalue()).decode("ascii")


def decode_manual_geometry_result(encoded: str) -> ManualGeometryResult:
    payload = str(encoded or "").strip()
    if not payload:
        raise ValueError("No saved manual geometry result is available")
    cache_key = hashlib.blake2b(
        payload.encode("ascii", errors="ignore"), digest_size=16
    ).hexdigest()
    with _RESULT_CACHE_LOCK:
        cached = _RESULT_CACHE.get(cache_key)
        if cached is not None:
            _RESULT_CACHE.move_to_end(cache_key)
            return cached
    try:
        raw = base64.b64decode(payload, validate=True)
        with np.load(BytesIO(raw), allow_pickle=False) as archive:
            name = (
                str(archive["name"][0])
                if "name" in archive
                else "Manual Geometry Result"
            )
            diagnostics_raw = (
                str(archive["diagnostics"][0])
                if "diagnostics" in archive
                else "{}"
            )
            result = ManualGeometryResult(
                GeometryData(
                    archive["vertices"], archive["indices"], name,
                    str(archive["uv_origin"][0]) if "uv_origin" in archive else "top-left",
                ),
                dict(json.loads(diagnostics_raw)),
            )
    except Exception as exc:
        raise ValueError("Saved manual geometry result is damaged") from exc
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[cache_key] = result
        _RESULT_CACHE.move_to_end(cache_key)
        total = sum(item.memory_bytes for item in _RESULT_CACHE.values())
        while total > _RESULT_CACHE_BUDGET and len(_RESULT_CACHE) > 1:
            _key, old = _RESULT_CACHE.popitem(last=False)
            total -= old.memory_bytes
    return result


def evaluate_manual_geometry_operation(
    source: GeometryData,
    parameters: Mapping[str, Any],
    context: GeometryEvalContext | None,
    *,
    parameter_names: tuple[str, ...],
    default_name: str,
    operation_name: str,
    metadata_prefix: str,
    operation: Callable[
        [GeometryData, Mapping[str, Any], GeometryEvalContext | None],
        ManualGeometryResult,
    ],
    include_normals_in_signature: bool = True,
    include_uvs_in_signature: bool = True,
) -> GeometryData:
    """Run or present one transactional manual geometry operation."""

    run_serial = int(parameters.get("_manual_run_serial", 0) or 0)
    completed_serial = int(parameters.get("_manual_completed_serial", 0) or 0)
    payload = str(parameters.get("_manual_result_data", "") or "")
    stored_signature = str(parameters.get("_manual_signature", "") or "")
    current_signature = geometry_operation_signature(
        source,
        parameters,
        parameter_names,
        include_normals=include_normals_in_signature,
        include_uvs=include_uvs_in_signature,
    )
    previous: ManualGeometryResult | None = None
    if payload:
        previous = decode_manual_geometry_result(payload)

    should_execute = run_serial > completed_serial
    if should_execute:
        try:
            if context is not None:
                context.progress(0, 100, f"Starting manual {operation_name.lower()}")
            result = operation(source, parameters, context)
            encoded = encode_manual_geometry_result(result)
            if context is not None:
                metadata: dict[str, Any] = {
                    "_manual_status": "Up to Date",
                    "_manual_completed_serial": run_serial,
                    "_manual_signature": current_signature,
                    "_manual_result_data": encoded,
                    "_manual_result_revision": hashlib.blake2b(
                        encoded.encode("ascii"), digest_size=20
                    ).hexdigest(),
                    "_manual_last_error": "",
                    "_manual_applied_parameters": {
                        name: parameters.get(name) for name in parameter_names
                    },
                }
                for key, value in result.diagnostics.items():
                    metadata[f"_{metadata_prefix}_{key}"] = value
                context.report_metadata(metadata)
            active = result
        except GeometryEvaluationCancelled:
            raise
        except Exception as exc:
            if previous is None:
                raise
            active = previous
            if context is not None:
                context.report_metadata(
                    {
                        "_manual_status": "Failed",
                        "_manual_last_error": f"{type(exc).__name__}: {exc}",
                        "_manual_completed_serial": run_serial,
                    }
                )
    elif previous is not None:
        active = previous
        status = "Up to Date" if stored_signature == current_signature else "Out of Date"
        if context is not None:
            context.report_metadata(
                {"_manual_status": status, "_manual_last_error": ""}
            )
    else:
        active = ManualGeometryResult(
            source.copy(name=str(parameters.get("name", default_name) or default_name)),
            {"backend": "Not run"},
        )
        if context is not None:
            context.report_metadata(
                {"_manual_status": "Not Run", "_manual_last_error": ""}
            )

    desired_name = str(parameters.get("name", default_name) or default_name)
    if active.geometry.name != desired_name:
        return active.geometry.copy(name=desired_name)
    return active.geometry
