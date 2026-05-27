from .. import icons
from .. import properties


def draw_manager_content(layout, context):
    preferences = properties.get_addon_preferences(context)

    if preferences is not None:
        properties.draw_visibility_settings(layout, preferences, include_sidebar=False)

    actions_box = layout.box()
    actions_box.label(text="Active Editor")
    actions_box.operator_context = "INVOKE_DEFAULT"
    actions_box.operator("floaty.detach_area", text="", **icons.get_detach_icon())


def draw_detached_window_list(layout, context, state_module):
    detached_box = layout.box()
    detached_box.label(text="Detached Windows")

    has_items = False
    for window, info in state_module.iter_detached_windows(context.window_manager):
        has_items = True
        row = detached_box.row(align=True)
        row.label(text=state_module.area_type_label(info["area_type"]))
        if context.window is not None and window.as_pointer() == context.window.as_pointer():
            row.operator("floaty.open_place_menu", text="", **icons.get_place_icon())

    if not has_items:
        detached_box.label(text="No detached windows tracked.")
