import bpy

from .. import icons
from .. import properties
from .. import state


_HEADER_TYPES = [
    "VIEW3D_HT_header",
    "OUTLINER_HT_header",
    "PROPERTIES_HT_header",
    "DOPESHEET_HT_header",
    "GRAPH_HT_header",
    "NLA_HT_header",
    "IMAGE_HT_header",
    "NODE_HT_header",
    "TEXT_HT_header",
    "CONSOLE_HT_header",
    "FILEBROWSER_HT_header",
    "CLIP_HT_header",
    "SEQUENCER_HT_header",
    "SPREADSHEET_HT_header",
]

_appended_headers = []


def _iter_header_types():
    for type_name in _HEADER_TYPES:
        header_type = getattr(bpy.types, type_name, None)
        if header_type is not None:
            yield header_type


def _is_floaty_header_draw_func(draw_func):
    return (
        getattr(draw_func, "__name__", "") == "draw_floaty_header_button" and
        getattr(draw_func, "__module__", "").endswith(".floaty.ui.headers")
    )


def _remove_floaty_header_draw_funcs(header_type):
    try:
        draw_funcs = header_type._dyn_ui_initialize()
    except AttributeError:
        return

    for draw_func in tuple(draw_funcs):
        if draw_func is draw_floaty_header_button or _is_floaty_header_draw_func(draw_func):
            header_type.remove(draw_func)


def draw_floaty_header_button(self, context):
    area = context.area
    window = context.window
    if (
        area is None or
        window is None or
        not state.supports_area(area.type) or
        not properties.should_show_header_button(context)
    ):
        return

    row = self.layout.row(align=True)

    if state.is_detached_window(window):
        row.operator("floaty.open_place_menu", text="", **icons.get_place_icon())
    else:
        row.operator_context = "INVOKE_DEFAULT"
        row.operator("floaty.detach_area", text="", **icons.get_detach_icon())


def register():
    global _appended_headers

    _appended_headers = []
    for header_type in _iter_header_types():
        _remove_floaty_header_draw_funcs(header_type)
        header_type.append(draw_floaty_header_button)
        _appended_headers.append(header_type)


def unregister():
    global _appended_headers

    for header_type in set((*_appended_headers, *_iter_header_types())):
        _remove_floaty_header_draw_funcs(header_type)
    _appended_headers = []
