"""Small UI translation layer for Bone Importer.

Blender property names are registered statically, so the panel uses this
module for dynamic bilingual labels and help text.
"""

from __future__ import annotations


LANG_EN = "EN"
LANG_ZH = "ZH"


TRANSLATIONS = {
    "panel.title": ("RX Export v3", "RX 导出 v3"),
    "setup.title": ("Export Setup", "导出设置"),
    "setup.output_dir": ("Output Dir", "输出目录"),
    "setup.capture_manifest": ("Capture Manifest", "捕获清单"),
    "setup.collection": ("RX Export Collection", "RX 导出集合"),
    "setup.create_collection": ("Create/Sync RX Collections", "创建/同步 RX 集合"),
    "setup.export": ("Export RX Package", "导出 RX 包"),
    "timeline.title": ("Timeline", "时间轴"),
    "timeline.clip": ("Clip", "动作"),
    "timeline.id": ("ID", "ID"),
    "timeline.start": ("Start", "开始"),
    "timeline.end": ("End", "结束"),
    "timeline.frame_step": ("Frame Step", "采样步长"),
    "timeline.derived_step": ("Scene FPS source: {fps:g}; derived runtime step: {step} present(s)", "源 FPS: {fps:g}; 推导运行步长: {step} 个 Present"),
    "preview.title": ("IB Preview", "IB 预览"),
    "preview.no_collection": ("Set an RX Export Collection.", "请先设置 RX 导出集合。"),
    "preview.expected": (
        "Expected child collections: hash-index_count-firstindex, optionally with partNN children.",
        "需要子集合命名为 hash-index_count-firstindex，可选 partNN 子集合。",
    ),
    "preview.ib": ("IB Collections: {count}", "IB 集合: {count}"),
    "preview.parts": ("Parts: {count}", "Part 数: {count}"),
    "preview.segments": ("Draw Segments: {count}", "绘制段: {count}"),
    "preview.geometry": ("Geometry Required: {count}", "需要导出几何: {count}"),
    "preview.source": ("Source Skin: {count}", "源模型蒙皮: {count}"),
    "preview.own": ("Own Skin: {count}", "自有骨骼蒙皮: {count}"),
    "preview.morph": ("Morph: {count}", "形态键: {count}"),
    "preview.preskin": ("Pre-Skin Bone: {count}", "骨骼预蒙皮: {count}"),
    "preview.skip": ("{key}: skip original", "{key}: 跳过原 draw"),
    "preview.keep": ("{key}: keep original", "{key}: 保留原 draw"),
    "preview.more": ("{count} more IB collection(s) hidden.", "还有 {count} 个 IB 集合未显示。"),
    "active.title": ("Active Context", "当前上下文"),
    "active.source_mesh": ("Source Mesh: {name}", "源网格: {name}"),
    "active.proxy_armature": ("Proxy Armature: {name}", "代理骨架: {name}"),
    "advanced.title": ("Active Mesh Advanced", "当前网格高级设置"),
    "advanced.no_mesh": ("Select a mesh inside an IB collection to edit object route settings.", "选择 IB 集合内的网格以编辑对象路线。"),
    "advanced.final_route": ("Final Draw Route", "最终绘制路线"),
    "advanced.preskin": ("Pre-Skin Bone", "骨骼预蒙皮"),
    "advanced.morph": ("Morph", "形态键"),
    "advanced.adapters": ("Runtime Adapters", "运行时适配"),
    "advanced.legacy_bone": ("Legacy Bone Map", "旧骨骼映射"),
    "defaults.title": ("Default Export Adapters", "默认导出适配"),
    "morph_defaults.title": ("Morph Defaults", "形态键默认值"),
    "utilities.title": ("Utilities", "工具"),
    "utilities.generate_proxy": ("Generate Slot Proxy", "生成槽位代理骨架"),
    "utilities.restore_groups": ("Restore Numeric Groups", "恢复数字顶点组"),
    "proxy.count": ("Proxy Bones: {count}", "代理骨骼数: {count}"),
    "proxy.active": ("Active Proxy Bone: {name}", "当前代理骨骼: {name}"),
}


def language_from_owner(owner) -> str:
    raw_value = str(getattr(owner, "bi_ui_language", "ZH") or "ZH").upper()
    return LANG_EN if raw_value == LANG_EN else LANG_ZH


def tr(owner, key: str, **kwargs) -> str:
    language = language_from_owner(owner)
    english, chinese = TRANSLATIONS.get(key, (key, key))
    template = english if language == LANG_EN else chinese
    return template.format(**kwargs) if kwargs else template
