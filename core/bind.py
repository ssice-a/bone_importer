"""Bind refresh helpers for proxy armatures."""

from .export import clear_previous_palette_cache
from .proxy import capture_proxy_bind_matrices


def refresh_bind_for_proxy_armature(proxy_armature):
    """Capture the current rest matrices as the new bind and clear previous cache."""
    captured_bone_count = capture_proxy_bind_matrices(proxy_armature)
    clear_previous_palette_cache(proxy_armature)
    return captured_bone_count
