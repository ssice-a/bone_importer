"""Addon entry point for the Bone Importer package."""

bl_info = {
    "name": "Bone Importer",
    "author": "OpenAI Codex",
    "version": (0, 4, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Bone Importer",
    "description": "Generate VS-T0 proxy bones and import/export VS-T0-compatible palette buffers.",
    "category": "Animation",
}

import bpy

from . import addon_operators, addon_panel, addon_properties


REGISTERED_CLASSES = (
    addon_operators.BI_OT_generate_proxy_rig,
    addon_operators.BI_OT_capture_bind,
    addon_operators.BI_OT_export_palette,
    addon_operators.BI_OT_import_palette,
    addon_operators.BI_OT_clear_previous_cache,
    addon_panel.VIEW3D_PT_bone_importer,
)


def register():
    """Register Blender properties, operators, and panels for the addon."""
    addon_properties.register_addon_properties()
    for blender_class in REGISTERED_CLASSES:
        bpy.utils.register_class(blender_class)


def unregister():
    """Unregister Blender properties, operators, and panels for the addon."""
    for blender_class in reversed(REGISTERED_CLASSES):
        bpy.utils.unregister_class(blender_class)
    addon_properties.unregister_addon_properties()


if __name__ == "__main__":
    register()
