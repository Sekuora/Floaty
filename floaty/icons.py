from pathlib import Path

import bpy
import bpy.utils.previews


_preview_collection = None
_ICON_FILES = {
    "attached": "blender_icon_window_atached.png",
    "detached": "blender_icon_window_detached.png",
}
_FALLBACK_ICONS = {
    "attached": "WINDOW",
    "detached": "WINDOW",
}


def register():
    global _preview_collection

    if _preview_collection is not None:
        return

    _preview_collection = bpy.utils.previews.new()
    icons_dir = Path(__file__).resolve().parents[1] / "assets" / "icons"
    for icon_name, file_name in _ICON_FILES.items():
        icon_path = icons_dir / file_name
        if icon_path.exists():
            _preview_collection.load(icon_name, str(icon_path), "IMAGE")


def unregister():
    global _preview_collection

    if _preview_collection is None:
        return

    bpy.utils.previews.remove(_preview_collection)
    _preview_collection = None


def _get_icon(icon_name):
    if _preview_collection is not None and icon_name in _preview_collection:
        return {"icon_value": _preview_collection[icon_name].icon_id}
    return {"icon": _FALLBACK_ICONS[icon_name]}


def get_detach_icon():
    return _get_icon("attached")


def get_place_icon():
    return _get_icon("detached")


def get_push_icon():
    return get_place_icon()
