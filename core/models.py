"""Data models shared across the plugin."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProxyRigGenerationResult:
    """Summary of generating one proxy rig."""

    source_mesh_name: str
    armature_name: str
    configured_bones: int
    max_slot: int
    slot_capacity: int
    skipped_groups: tuple[str, ...] = field(default_factory=tuple)
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProxyBindCaptureResult:
    """Summary of refreshing bind matrices for one proxy rig."""

    armature_name: str
    captured_bones: int
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchBindRefreshResult:
    """Summary of refreshing bind matrices for multiple proxy rigs."""

    selected_armatures: int
    refreshed_armatures: int
    refreshed_bones: int
    failed_armatures: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PaletteExportResult:
    """Summary of exporting one static palette file."""

    armature_name: str
    binary_path: str
    metadata_path: str
    exported_bones: int
    overflow_bones: int
    metadata: dict
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchPaletteExportResult:
    """Summary of exporting one or more static palette parts."""

    binary_path: str
    metadata_path: str
    selected_armatures: int
    exported_armatures: int
    exported_bones: int
    overflow_bones: int
    failed_armatures: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict | None = None


@dataclass(frozen=True)
class PaletteImportResult:
    """Summary of importing one static palette segment."""

    armature_name: str
    binary_path: str
    imported_bones: int
    missing_rows: int
    segment: str
    metadata: dict | None = None
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AnimationExportResult:
    """Summary of exporting one TQS animation buffer set."""

    armature_name: str
    tqs_path: str
    bind_path: str
    meta_path: str
    frame_count: int
    bone_count: int
    metadata: dict
    debug_metadata_path: str = ""


@dataclass(frozen=True)
class BatchAnimationExportResult:
    """Summary of exporting TQS animation buffers for multiple proxy rigs."""

    output_directory: str
    selected_armatures: int
    exported_armatures: int
    total_frames: int
    total_exported_bones: int
    sampled_frames: int = 0
    elapsed_seconds: float = 0.0
    frame_set_seconds: float = 0.0
    frame_write_seconds: float = 0.0
    finalize_seconds: float = 0.0
    other_seconds: float = 0.0
    failed_armatures: tuple[str, ...] = field(default_factory=tuple)
    exported_files: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchProxyRigGenerationResult:
    """Summary of generating multiple proxy rigs."""

    generated_meshes: int
    generated_armatures: int
    generated_bones: int
    skipped_meshes: tuple[str, ...] = field(default_factory=tuple)
    skipped_details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchPaletteImportResult:
    """Summary of importing one palette into multiple proxy rigs."""

    binary_path: str
    selected_armatures: int
    imported_armatures: int
    imported_bones: int
    failed_armatures: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoadedPaletteFile:
    """Palette rows loaded from disk."""

    binary_path: str
    rows: list[tuple[float, float, float, float]]
    metadata: dict | None = None
    row_start: int = 0


@dataclass(frozen=True)
class DebugDumpResult:
    """Summary of a console debug dump."""

    armature_name: str
    sampled_bones: int
    has_import_data: bool
