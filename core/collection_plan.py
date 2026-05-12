"""Collection-backed export target discovery."""

from __future__ import annotations

from .context import find_proxy_armature_for_object


CB1_OVERRIDE_INHERIT = "INHERIT"
CB1_OVERRIDE_NONE = "NONE"
CB1_OVERRIDE_EYELASH = "EYELASH"

CB1_OVERRIDE_ITEMS = (
    (CB1_OVERRIDE_INHERIT, "Inherit", "Inherit the parent RX collection CB1 override; root defaults to none"),
    (CB1_OVERRIDE_NONE, "None", "Do not bind a special cb1 flag resource before RedirectCB1"),
    (CB1_OVERRIDE_EYELASH, "Eyelash", "Bind ResourceCB1Flag_Eyelash before RedirectCB1 for eyelash/eye VS branches"),
)


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


def normalize_cb1_override(value: str, inherited_value: str = CB1_OVERRIDE_NONE) -> str:
    """Resolve one collection CB1 override enum value to an effective setting."""
    normalized_value = str(value or CB1_OVERRIDE_INHERIT).upper()
    if normalized_value == CB1_OVERRIDE_INHERIT:
        return inherited_value if inherited_value in {CB1_OVERRIDE_NONE, CB1_OVERRIDE_EYELASH} else CB1_OVERRIDE_NONE
    if normalized_value == CB1_OVERRIDE_EYELASH:
        return CB1_OVERRIDE_EYELASH
    return CB1_OVERRIDE_NONE


def cb1_override_by_proxy_armature_name_from_collection(collection) -> dict[str, str]:
    """Return effective collection-level CB1 override values for resolved proxy armatures."""
    if collection is None:
        return {}

    override_by_proxy_name: dict[str, str] = {}

    def assign_proxy_override(proxy_armature, effective_override: str):
        if proxy_armature is None:
            return
        if int(getattr(proxy_armature, "bi_part_id", -1)) < 0:
            return
        proxy_name = str(getattr(proxy_armature, "name_full", getattr(proxy_armature, "name", "")) or "")
        if not proxy_name:
            return
        previous_override = override_by_proxy_name.get(proxy_name, CB1_OVERRIDE_NONE)
        # If the same proxy appears in multiple collections, prefer the explicit special path over none.
        if previous_override == CB1_OVERRIDE_NONE or effective_override != CB1_OVERRIDE_NONE:
            override_by_proxy_name[proxy_name] = effective_override

    def walk(current_collection, inherited_override: str):
        raw_override = getattr(current_collection, "bi_cb1_override", CB1_OVERRIDE_INHERIT)
        effective_override = normalize_cb1_override(raw_override, inherited_override)
        for obj in getattr(current_collection, "objects", []) or []:
            assign_proxy_override(find_proxy_armature_for_object(obj), effective_override)
        for child in getattr(current_collection, "children", []) or []:
            walk(child, effective_override)

    walk(collection, CB1_OVERRIDE_NONE)
    return override_by_proxy_name
