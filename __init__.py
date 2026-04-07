"""Bone Importer 插件入口。"""

bl_info = {
    "name": "Bone Importer",
    "author": "OpenAI Codex",
    "version": (0, 6, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Bone Importer",
    "description": "Generate VS-T0 proxy bones and import/export static palettes or sparse animation clips.",
    "category": "Animation",
}

import bpy

from . import operators, panel, properties


REGISTERED_CLASSES = (
    operators.BI_OT_generate_proxy_rig,
    operators.BI_OT_refresh_bind,
    operators.BI_OT_export_palette,
    operators.BI_OT_export_animation,
    operators.BI_OT_import_palette,
    operators.BI_OT_clear_previous_cache,
    operators.BI_OT_dump_debug,
    panel.VIEW3D_PT_bone_importer,
)


def register():
    """注册插件属性、操作器和面板。"""
    properties.register_addon_properties()
    for blender_class in REGISTERED_CLASSES:
        bpy.utils.register_class(blender_class)


def unregister():
    """卸载插件注册过的属性、操作器和面板。"""
    for blender_class in reversed(REGISTERED_CLASSES):
        bpy.utils.unregister_class(blender_class)
    properties.unregister_addon_properties()


if __name__ == "__main__":
    register()
