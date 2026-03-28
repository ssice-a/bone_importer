"""Bone Importer 的核心可复用接口。"""

from .context import (
    apply_part_id_layout,
    build_part_layout_from_id,
    capture_selection_state,
    ensure_mesh_parented_to_proxy_armature,
    find_proxy_armature_for_object,
    find_source_mesh_for_object,
    list_selected_proxy_armatures,
    make_object_active,
    restore_selection_state,
)
from .debug import build_proxy_debug_snapshot, print_debug_snapshot
from .export import (
    build_palette_export_package,
    cache_current_palette_segment,
    clear_previous_palette_cache,
    list_exportable_proxy_pose_bones,
)
from .importer import apply_palette_segment_to_proxy_armature, resolve_palette_segment_window
from .io import (
    build_metadata_path_from_binary_path,
    load_palette_file,
    read_palette_metadata_from_file,
    write_palette_package_to_disk,
)
from .layout import (
    build_identity_buffer_rows,
    build_matrix_from_flat_values,
    build_matrix_from_palette_rows,
    calculate_slot_capacity_for_part_size,
    convert_matrix_to_palette_rows,
    flatten_matrix_to_list,
)
from .models import (
    BatchPaletteImportResult,
    BatchProxyRigGenerationResult,
    DebugDumpResult,
    PaletteExportResult,
    PaletteImportResult,
    ProxyBindCaptureResult,
    ProxyRigGenerationResult,
)
from .proxy import (
    build_proxy_armature_name,
    build_proxy_bone_definitions,
    capture_proxy_bind_matrices,
    configure_proxy_pose_bones,
    ensure_proxy_armature_modifier,
    get_or_create_proxy_armature,
    list_other_armature_modifier_names,
    parse_slot_id_from_name,
    rebuild_proxy_edit_bones,
)
from .transform import convert_matrix_from_blender_to_game, convert_matrix_from_game_to_blender
from .workflow import (
    capture_bind_for_active_proxy,
    clear_previous_palette_for_active_proxy,
    dump_debug_for_active_proxy,
    export_palette_for_active_proxy,
    generate_proxy_rig_for_mesh,
    generate_proxy_rig_from_active_mesh,
    generate_proxy_rigs_from_selected_meshes,
    import_palette_for_active_proxy,
    import_palette_for_proxy_armature,
    import_palette_for_selected_proxy_armatures,
)
