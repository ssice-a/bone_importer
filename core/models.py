"""在各模块之间传递结果时使用的数据模型。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProxyRigGenerationResult:
    """代理骨架生成结果摘要。"""

    source_mesh_name: str
    armature_name: str
    configured_bones: int
    max_slot: int
    slot_capacity: int
    skipped_groups: tuple[str, ...] = field(default_factory=tuple)
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProxyBindCaptureResult:
    """Bind 捕获结果摘要。"""

    armature_name: str
    captured_bones: int
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PaletteExportResult:
    """调色板导出到磁盘后的结果。"""

    armature_name: str
    binary_path: str
    metadata_path: str
    exported_bones: int
    overflow_bones: int
    metadata: dict
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchPaletteExportResult:
    """把多个已选代理骨架导出并合并到同一份大缓冲后的结果摘要。"""

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
    """把调色板导入到代理骨架后的结果。"""

    armature_name: str
    binary_path: str
    imported_bones: int
    missing_rows: int
    segment: str
    metadata: dict | None = None
    other_armature_modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchProxyRigGenerationResult:
    """批量生成多个代理骨架后的结果摘要。"""

    generated_meshes: int
    generated_armatures: int
    generated_bones: int
    skipped_meshes: tuple[str, ...] = field(default_factory=tuple)
    skipped_details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BatchPaletteImportResult:
    """把同一份调色板导入到多个已选骨架后的结果摘要。"""

    binary_path: str
    selected_armatures: int
    imported_armatures: int
    imported_bones: int
    failed_armatures: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoadedPaletteFile:
    """从磁盘读取到的调色板数据和可选元数据。"""

    binary_path: str
    rows: list[tuple[float, float, float, float]]
    metadata: dict | None = None
    row_start: int = 0


@dataclass(frozen=True)
class DebugDumpResult:
    """导出调试快照后的结果摘要。"""

    armature_name: str
    sampled_bones: int
    has_import_data: bool
