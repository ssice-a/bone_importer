"""Collection-backed export target discovery."""

from __future__ import annotations

from .context import find_proxy_armature_for_object


def iter_collection_objects_recursive(collection):
    """Yield unique objects stored under an export collection tree."""
    if collection is None:
        return
    seen_names: set[str] = set()

    def walk(current_collection):
        for obj in getattr(current_collection, "objects", []) or []:
            object_name = str(getattr(obj, "name_full", getattr(obj, "name", "")) or "")
            if object_name in seen_names:
                continue
            seen_names.add(object_name)
            yield obj
        for child in getattr(current_collection, "children", []) or []:
            yield from walk(child)

    yield from walk(collection)


def proxy_armatures_from_export_collection(collection):
    """Resolve proxy armatures represented by objects inside the collection tree."""
    proxy_armatures = {}
    for obj in iter_collection_objects_recursive(collection):
        proxy_armature = find_proxy_armature_for_object(obj)
        if proxy_armature is None:
            continue
        if int(getattr(proxy_armature, "bi_part_id", -1)) < 0:
            continue
        proxy_armatures[proxy_armature.name_full] = proxy_armature
    return tuple(
        sorted(
            proxy_armatures.values(),
            key=lambda armature: (int(getattr(armature, "bi_part_id", -1)), armature.name),
        )
    )


def count_collection_meshes(collection) -> int:
    """Count mesh objects under the collection tree for panel feedback."""
    return sum(1 for obj in iter_collection_objects_recursive(collection) if getattr(obj, "type", "") == "MESH")
