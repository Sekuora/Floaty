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

    for type_name in _HEADER_TYPES:
        header_type = getattr(bpy.types, type_name, None)
        if header_type is None or header_type in _appended_headers:
            continue
        header_type.append(draw_floaty_header_button)
        _appended_headers.append(header_type)


def unregister():
    global _appended_headers

    for header_type in _appended_headers:
        try:
            header_type.remove(draw_floaty_header_button)
        except (AttributeError, ValueError):
            pass
    _appended_headers = []
