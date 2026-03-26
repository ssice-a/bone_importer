"""Typed result models shared across addon modules."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProxyRigGenerationResult:
    """Summary of a generated proxy rig."""

    source_mesh_name: str
    armature_name: str
    configured_bones: int
    max_slot: int
    slot_capacity: int
    skipped_groups: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProxyBindCaptureResult:
    """Summary of a bind capture pass."""

    armature_name: str
    captured_bones: int


@dataclass(frozen=True)
class PaletteExportResult:
    """Result of exporting a palette buffer to disk."""

    armature_name: str
    binary_path: str
    metadata_path: str
    exported_bones: int
    overflow_bones: int
    metadata: dict


@dataclass(frozen=True)
class PaletteImportResult:
    """Result of importing a palette buffer onto a proxy rig."""

    armature_name: str
    binary_path: str
    imported_bones: int
    missing_rows: int
    segment: str
    metadata: dict | None = None


@dataclass(frozen=True)
class LoadedPaletteFile:
    """Binary palette rows plus optional JSON metadata loaded from disk."""

    binary_path: str
    rows: list[tuple[float, float, float, float]]
    metadata: dict | None = None
