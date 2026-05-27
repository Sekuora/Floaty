import bpy


HEADER_PREFERENCE_ITEMS = (
    ("VIEW_3D", "show_header_view3d", "3D View", "VIEW3D"),
    ("OUTLINER", "show_header_outliner", "Outliner", "OUTLINER"),
    ("PROPERTIES", "show_header_properties", "Properties", "PROPERTIES"),
    ("DOPESHEET_EDITOR", "show_header_dopesheet", "Dope Sheet", "ACTION"),
    ("GRAPH_EDITOR", "show_header_graph", "Graph Editor", "GRAPH"),
    ("NLA_EDITOR", "show_header_nla", "NLA", "NLA"),
    ("IMAGE_EDITOR", "show_header_image", "Image Editor", "IMAGE"),
    ("NODE_EDITOR", "show_header_node", "Node Editor", "NODETREE"),
    ("TEXT_EDITOR", "show_header_text", "Text Editor", "TEXT"),
    ("CONSOLE", "show_header_console", "Python Console", "CONSOLE"),
    ("FILE_BROWSER", "show_header_filebrowser", "File Browser", "FILEBROWSER"),
    ("CLIP_EDITOR", "show_header_clip", "Movie Clip", "TRACKER"),
    ("SEQUENCE_EDITOR", "show_header_sequencer", "Sequencer", "SEQUENCE"),
    ("SPREADSHEET", "show_header_spreadsheet", "Spreadsheet", "SPREADSHEET"),
)


def _tag_redraw_on_update(_self, context):
    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        return

    for window in window_manager.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            area.tag_redraw()


def _addon_package_name():
    package_name = __package__ or ""
    if package_name.endswith(".floaty"):
        return package_name.rsplit(".floaty", 1)[0]
    return package_name.split(".")[0]


class FLOATY_PG_workspace_snapshot(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="Workspace Snapshot",
    )
    workspace_name: bpy.props.StringProperty(
        name="Workspace",
        default="",
    )
    summary: bpy.props.StringProperty(
        name="Summary",
        default="",
    )
    data_json: bpy.props.StringProperty(
        name="Snapshot Data",
        default="{}",
    )


class FLOATY_PG_settings(bpy.types.PropertyGroup):
    snapshot_name: bpy.props.StringProperty(
        name="Snapshot Name",
        description="Name for the next workspace snapshot",
        default="Workspace Snapshot",
    )
    active_snapshot_index: bpy.props.IntProperty(
        name="Active Snapshot",
        default=0,
        min=0,
    )


class FLOATY_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = _addon_package_name()

    show_sidebar_panel: bpy.props.BoolProperty(
        name="Show Sidebar Panel",
        description="Show Floaty in the 3D View sidebar",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_view3d: bpy.props.BoolProperty(
        name="3D View",
        description="Show the Floaty button in 3D View headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_outliner: bpy.props.BoolProperty(
        name="Outliner",
        description="Show the Floaty button in Outliner headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_properties: bpy.props.BoolProperty(
        name="Properties",
        description="Show the Floaty button in Properties headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_dopesheet: bpy.props.BoolProperty(
        name="Dope Sheet",
        description="Show the Floaty button in Dope Sheet headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_graph: bpy.props.BoolProperty(
        name="Graph Editor",
        description="Show the Floaty button in Graph Editor headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_nla: bpy.props.BoolProperty(
        name="NLA",
        description="Show the Floaty button in NLA headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_image: bpy.props.BoolProperty(
        name="Image Editor",
        description="Show the Floaty button in Image Editor headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_node: bpy.props.BoolProperty(
        name="Node Editor",
        description="Show the Floaty button in Node Editor headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_text: bpy.props.BoolProperty(
        name="Text Editor",
        description="Show the Floaty button in Text Editor headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_console: bpy.props.BoolProperty(
        name="Python Console",
        description="Show the Floaty button in Python Console headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_filebrowser: bpy.props.BoolProperty(
        name="File Browser",
        description="Show the Floaty button in File Browser headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_clip: bpy.props.BoolProperty(
        name="Movie Clip",
        description="Show the Floaty button in Movie Clip headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_sequencer: bpy.props.BoolProperty(
        name="Sequencer",
        description="Show the Floaty button in Sequencer headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    show_header_spreadsheet: bpy.props.BoolProperty(
        name="Spreadsheet",
        description="Show the Floaty button in Spreadsheet headers",
        default=True,
        update=_tag_redraw_on_update,
    )
    workspace_snapshots: bpy.props.CollectionProperty(
        type=FLOATY_PG_workspace_snapshot,
    )

    def draw(self, context):
        layout = self.layout
        draw_visibility_settings(layout, self)


def header_preference_prop_for_area(area_type):
    for item_area_type, prop_name, _label, _icon in HEADER_PREFERENCE_ITEMS:
        if item_area_type == area_type:
            return prop_name
    return None


def should_show_header_button(context):
    preferences = get_addon_preferences(context)
    area = getattr(context, "area", None)
    if preferences is None or area is None:
        return True

    prop_name = header_preference_prop_for_area(area.type)
    if prop_name is None:
        return True
    return getattr(preferences, prop_name, True)


def should_show_sidebar_panel(context):
    preferences = get_addon_preferences(context)
    if preferences is None:
        return True
    return preferences.show_sidebar_panel


def draw_visibility_settings(layout, preferences, include_sidebar=True):
    if include_sidebar:
        panel_box = layout.box()
        panel_box.label(text="Sidebar")
        panel_box.prop(preferences, "show_sidebar_panel", toggle=True)

    header_box = layout.box()
    header_box.label(text="Header Buttons")
    grid = header_box.grid_flow(
        row_major=True,
        columns=2,
        even_columns=True,
        even_rows=False,
        align=True,
    )
    for _area_type, prop_name, label, icon in HEADER_PREFERENCE_ITEMS:
        grid.prop(preferences, prop_name, text=label, icon=icon, toggle=True)


def get_addon_preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(_addon_package_name())
    if addon is not None:
        return addon.preferences

    for addon in context.preferences.addons:
        preferences = getattr(addon, "preferences", None)
        if isinstance(preferences, FLOATY_AddonPreferences):
            return preferences
    return None


def get_workspace_snapshots(context=None):
    preferences = get_addon_preferences(context)
    if preferences is None:
        return None
    return preferences.workspace_snapshots


def register():
    bpy.types.WindowManager.floaty_settings = bpy.props.PointerProperty(type=FLOATY_PG_settings)


def unregister():
    if hasattr(bpy.types.WindowManager, "floaty_settings"):
        del bpy.types.WindowManager.floaty_settings
