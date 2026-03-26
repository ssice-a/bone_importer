"""Reusable core helpers for the Bone Importer addon."""

from .coordinate_conversion import (
    build_blender_to_game_correction_matrix,
    build_game_to_blender_correction_matrix,
    convert_matrix_from_blender_to_game,
    convert_matrix_from_game_to_blender,
    describe_coordinate_conversion,
)
from .object_context import (
    copy_layout_settings,
    find_layout_settings_owner,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    make_object_active,
)
from .palette_export import (
    build_palette_export_package,
    cache_current_palette_segment,
    clear_previous_palette_cache,
    list_exportable_proxy_pose_bones,
)
from .palette_file_io import (
    build_metadata_path_from_binary_path,
    load_palette_file,
    read_palette_metadata_from_file,
    read_palette_rows_from_file,
    resolve_palette_export_paths,
    write_palette_package_to_disk,
)
from .palette_import import apply_palette_segment_to_proxy_armature, resolve_palette_segment_window
from .palette_layout import (
    build_empty_palette_segment,
    build_identity_buffer_rows,
    build_matrix_from_flat_values,
    build_matrix_from_palette_rows,
    calculate_slot_capacity_for_part_size,
    convert_matrix_to_palette_rows,
    flatten_matrix_to_list,
)
from .proxy_rig import (
    build_proxy_armature_name,
    build_proxy_bone_definitions,
    capture_proxy_bind_matrices,
    configure_proxy_pose_bones,
    ensure_proxy_armature_modifier,
    get_or_create_proxy_armature,
    parse_slot_id_from_name,
    rebuild_proxy_edit_bones,
)
from .result_models import (
    LoadedPaletteFile,
    PaletteExportResult,
    PaletteImportResult,
    ProxyBindCaptureResult,
    ProxyRigGenerationResult,
)
from .workflow_steps import (
    capture_bind_for_active_proxy,
    clear_previous_palette_for_active_proxy,
    export_palette_for_active_proxy,
    generate_proxy_rig_from_active_mesh,
    import_palette_for_active_proxy,
)
