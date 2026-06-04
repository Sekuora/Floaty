import bpy

from . import state


_PLACEMENT_ITEMS = (
    ("TOP", "Above"),
    ("BOTTOM", "Below"),
    ("LEFT", "Left"),
    ("RIGHT", "Right"),
)
_ABSOLUTE_PLACEMENT_ITEMS = (
    ("LEFT", "Far Left"),
    ("RIGHT", "Far Right"),
    ("TOP", "Above All"),
    ("BOTTOM", "Below All"),
)
_MOVE_PLACEMENT_ITEMS = (
    ("TOP", "Above"),
    ("BOTTOM", "Below"),
    ("LEFT", "Left"),
    ("RIGHT", "Right"),
)
_MOVE_ABSOLUTE_PLACEMENT_ITEMS = (
    ("LEFT", "Far Left"),
    ("RIGHT", "Far Right"),
    ("TOP", "Above All"),
    ("BOTTOM", "Below All"),
)
_PLACEMENT_ICONS = {
    "TOP": "TRIA_UP",
    "BOTTOM": "TRIA_DOWN",
    "LEFT": "TRIA_LEFT",
    "RIGHT": "TRIA_RIGHT",
}
_ABSOLUTE_PLACEMENT_ICONS = {
    "TOP": "TRIA_UP_BAR",
    "BOTTOM": "TRIA_DOWN_BAR",
    "LEFT": "TRIA_LEFT_BAR",
    "RIGHT": "TRIA_RIGHT_BAR",
}
_MAX_PLACE_TARGET_MENUS = 64
_active_place_menu_targets = []
_active_move_menu_targets = []
_active_move_source = {}


def _placement_icon(placement, absolute=False):
    if absolute:
        return _ABSOLUTE_PLACEMENT_ICONS.get(placement, "NONE")
    return _PLACEMENT_ICONS.get(placement, "NONE")


class FLOATY_OT_detach_area(bpy.types.Operator):
    bl_idname = "floaty.detach_area"
    bl_label = "Float"
    bl_description = "Duplicate this editor into a new Blender window"

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.window is not None and
            not state.is_layout_operation_pending() and
            not state.is_detached_window(context.window) and
            state.supports_area(context.area.type)
        )

    def execute(self, context):
        if state.is_detached_window(context.window):
            self.report({"ERROR"}, "This editor is already detached")
            return {"CANCELLED"}

        before_window_ptrs = state.active_window_ptrs(context.window_manager)
        source_window_ptr = context.window.as_pointer()
        source_area_ptr = context.area.as_pointer()
        area_type = context.area.type

        result = bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
        if "FINISHED" in result:
            state.schedule_finalize_detach(
                context.window_manager,
                before_window_ptrs,
                source_window_ptr,
                source_area_ptr,
                area_type,
            )
        return result

    def invoke(self, context, event):
        if event.shift:
            if not FLOATY_OT_open_move_menu.poll(context):
                self.report({"ERROR"}, "Floaty could not move this editor")
                return {"CANCELLED"}
            return bpy.ops.floaty.open_move_menu()

        return self.execute(context)


class FLOATY_MT_place_detached_window(bpy.types.Menu):
    bl_idname = "FLOATY_MT_place_detached_window"
    bl_label = "Place Editor"

    def draw(self, context):
        layout = self.layout
        global _active_place_menu_targets

        targets = list(state.iter_placeable_areas(context.window_manager, context.window))
        _active_place_menu_targets = targets[:_MAX_PLACE_TARGET_MENUS]

        if not _active_place_menu_targets:
            layout.label(text="No open editors are available.")
            return

        for placement, label in _ABSOLUTE_PLACEMENT_ITEMS:
            operator = layout.operator(
                "floaty.place_detached_window_absolute",
                text=label,
                icon=_placement_icon(placement, absolute=True),
            )
            operator.placement = placement

        layout.separator()

        for index, target in enumerate(_active_place_menu_targets):
            layout.menu(
                f"FLOATY_MT_place_detached_window_target_{index}",
                text=target["label"],
            )

        if len(targets) > _MAX_PLACE_TARGET_MENUS:
            layout.separator()
            layout.label(text="More editors exist than this menu can show.")


class FLOATY_MT_move_active_editor(bpy.types.Menu):
    bl_idname = "FLOATY_MT_move_active_editor"
    bl_label = "Move Active Editor"

    def draw(self, context):
        layout = self.layout
        global _active_move_menu_targets

        source_window_ptr = _active_move_source.get("window_ptr")
        source_area_ptr = _active_move_source.get("area_ptr")
        targets = []
        for target in state.iter_placeable_areas(context.window_manager, None):
            if (
                target["window"].as_pointer() == source_window_ptr and
                target["area"].as_pointer() == source_area_ptr
            ):
                continue
            targets.append(target)

        _active_move_menu_targets = targets[:_MAX_PLACE_TARGET_MENUS]
        if not _active_move_menu_targets:
            layout.label(text="No destination editors are available.")
            return

        for placement, label in _MOVE_ABSOLUTE_PLACEMENT_ITEMS:
            operator = layout.operator(
                "floaty.move_active_editor_absolute",
                text=label,
                icon=_placement_icon(placement, absolute=True),
            )
            operator.source_window_ptr = str(source_window_ptr)
            operator.source_area_ptr = str(source_area_ptr)
            operator.placement = placement

        layout.separator()

        for index, target in enumerate(_active_move_menu_targets):
            layout.menu(
                f"FLOATY_MT_move_active_editor_target_{index}",
                text=target["label"],
            )

        if len(targets) > _MAX_PLACE_TARGET_MENUS:
            layout.separator()
            layout.label(text="More editors exist than this menu can show.")


class FLOATY_OT_open_place_menu(bpy.types.Operator):
    bl_idname = "floaty.open_place_menu"
    bl_label = "Open Place Menu"
    bl_description = "Choose an editor and where to place this detached editor"

    @classmethod
    def poll(cls, context):
        return (
            context.window is not None and
            state.is_detached_window(context.window) and
            not state.is_layout_operation_pending() and
            state.has_placeable_areas(context.window_manager, context.window)
        )

    def execute(self, context):
        return bpy.ops.wm.call_menu(name="FLOATY_MT_place_detached_window")


class FLOATY_OT_open_push_menu(bpy.types.Operator):
    bl_idname = "floaty.open_push_menu"
    bl_label = "Open Place Menu"
    bl_description = "Choose an editor and where to place this detached editor"

    @classmethod
    def poll(cls, context):
        return FLOATY_OT_open_place_menu.poll(context)

    def execute(self, context):
        return bpy.ops.floaty.open_place_menu()


class FLOATY_OT_open_move_menu(bpy.types.Operator):
    bl_idname = "floaty.open_move_menu"
    bl_label = "Open Move Menu"
    bl_description = "Move this editor to another location in the current layout"

    @classmethod
    def poll(cls, context):
        return (
            context.window is not None and
            context.area is not None and
            context.window.screen is not None and
            not state.is_detached_window(context.window) and
            not state.is_layout_operation_pending() and
            state.supports_area(context.area.type) and
            len(context.window.screen.areas) > 1 and
            state.has_placeable_areas(context.window_manager, None)
        )

    def execute(self, context):
        global _active_move_source
        _active_move_source = {
            "window_ptr": context.window.as_pointer(),
            "area_ptr": context.area.as_pointer(),
        }
        return bpy.ops.wm.call_menu(name="FLOATY_MT_move_active_editor")


class _FLOATY_MT_place_target_base:
    target_index = -1

    def draw(self, context):
        if not (0 <= self.target_index < len(_active_place_menu_targets)):
            self.layout.label(text="Target editor is no longer available.")
            return

        target = _active_place_menu_targets[self.target_index]
        for placement, label in _PLACEMENT_ITEMS:
            operator = self.layout.operator(
                "floaty.place_detached_window",
                text=label,
                icon=_placement_icon(placement),
            )
            operator.target_window_ptr = str(target["window"].as_pointer())
            operator.target_area_ptr = str(target["area"].as_pointer())
            operator.placement = placement


class _FLOATY_MT_move_target_base:
    target_index = -1

    def draw(self, context):
        if not (0 <= self.target_index < len(_active_move_menu_targets)):
            self.layout.label(text="Target editor is no longer available.")
            return

        target = _active_move_menu_targets[self.target_index]
        for placement, label in _MOVE_PLACEMENT_ITEMS:
            operator = self.layout.operator(
                "floaty.move_active_editor",
                text=label,
                icon=_placement_icon(placement),
            )
            operator.source_window_ptr = str(_active_move_source.get("window_ptr"))
            operator.source_area_ptr = str(_active_move_source.get("area_ptr"))
            operator.target_window_ptr = str(target["window"].as_pointer())
            operator.target_area_ptr = str(target["area"].as_pointer())
            operator.placement = placement


class FLOATY_OT_place_detached_window(bpy.types.Operator):
    bl_idname = "floaty.place_detached_window"
    bl_label = "Place Editor"
    bl_description = "Place this detached editor on the chosen side of the selected editor, then close the detached window"

    target_window_ptr: bpy.props.StringProperty()
    target_area_ptr: bpy.props.StringProperty()
    placement: bpy.props.EnumProperty(
        name="Placement",
        items=[
            ("TOP", "Place Above", "Place this detached editor above the selected editor"),
            ("BOTTOM", "Place Below", "Place this detached editor below the selected editor"),
            ("LEFT", "Place Left", "Place this detached editor to the left of the selected editor"),
            ("RIGHT", "Place Right", "Place this detached editor to the right of the selected editor"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return (
            context.window is not None and
            state.is_detached_window(context.window) and
            not state.is_layout_operation_pending() and
            state.has_placeable_areas(context.window_manager, context.window)
        )

    def execute(self, context):
        if not state.place_detached_window(
            context.window_manager,
            context.window,
            int(self.target_window_ptr),
            int(self.target_area_ptr),
            self.placement,
        ):
            self.report({"ERROR"}, "Floaty could not place this editor in the selected location")
            return {"CANCELLED"}

        state.retire_detached_window(context.window)
        state.tag_redraw_all(context.window_manager)
        return bpy.ops.wm.window_close()


class FLOATY_OT_place_detached_window_absolute(bpy.types.Operator):
    bl_idname = "floaty.place_detached_window_absolute"
    bl_label = "Place Editor at Edge"
    bl_description = "Place this detached editor at the outer edge of all available editors"

    placement: bpy.props.EnumProperty(
        name="Placement",
        items=[
            ("TOP", "Place Above All", "Place this detached editor above the topmost editor"),
            ("BOTTOM", "Place Below All", "Place this detached editor below the bottommost editor"),
            ("LEFT", "Place Far Left", "Place this detached editor to the left of the leftmost editor"),
            ("RIGHT", "Place Far Right", "Place this detached editor to the right of the rightmost editor"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return (
            context.window is not None and
            state.is_detached_window(context.window) and
            not state.is_layout_operation_pending() and
            state.has_placeable_areas(context.window_manager, context.window)
        )

    def execute(self, context):
        if not state.place_detached_window_absolute(
            context.window_manager,
            context.window,
            self.placement,
        ):
            self.report({"ERROR"}, "Floaty could not place this editor at the selected edge")
            return {"CANCELLED"}

        state.retire_detached_window(context.window)
        state.tag_redraw_all(context.window_manager)
        return bpy.ops.wm.window_close()


class FLOATY_OT_move_active_editor(bpy.types.Operator):
    bl_idname = "floaty.move_active_editor"
    bl_label = "Move Editor"
    bl_description = "Move this editor to the chosen side of the selected editor"

    source_window_ptr: bpy.props.StringProperty()
    source_area_ptr: bpy.props.StringProperty()
    target_window_ptr: bpy.props.StringProperty()
    target_area_ptr: bpy.props.StringProperty()
    placement: bpy.props.EnumProperty(
        name="Placement",
        items=[
            ("TOP", "Move Above", "Move this editor above the selected editor"),
            ("BOTTOM", "Move Below", "Move this editor below the selected editor"),
            ("LEFT", "Move Left", "Move this editor to the left of the selected editor"),
            ("RIGHT", "Move Right", "Move this editor to the right of the selected editor"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return not state.is_layout_operation_pending()

    def execute(self, context):
        source_window = state._find_window_by_ptr(context.window_manager, int(self.source_window_ptr))
        source_area = state._find_area_by_ptr(
            source_window.screen if source_window is not None else None,
            int(self.source_area_ptr),
        )
        if not state.move_area_to_target(
            context.window_manager,
            source_window,
            source_area,
            int(self.target_window_ptr),
            int(self.target_area_ptr),
            self.placement,
        ):
            self.report({"ERROR"}, "Floaty could not move this editor")
            return {"CANCELLED"}

        state.tag_redraw_all(context.window_manager)
        return {"FINISHED"}


class FLOATY_OT_move_active_editor_absolute(bpy.types.Operator):
    bl_idname = "floaty.move_active_editor_absolute"
    bl_label = "Move Editor to Edge"
    bl_description = "Move this editor to the outer edge of all available editors"

    source_window_ptr: bpy.props.StringProperty()
    source_area_ptr: bpy.props.StringProperty()
    placement: bpy.props.EnumProperty(
        name="Placement",
        items=[
            ("TOP", "Move Above All", "Move this editor above the topmost editor"),
            ("BOTTOM", "Move Below All", "Move this editor below the bottommost editor"),
            ("LEFT", "Move Far Left", "Move this editor to the left edge"),
            ("RIGHT", "Move Far Right", "Move this editor to the right edge"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return not state.is_layout_operation_pending()

    def execute(self, context):
        source_window = state._find_window_by_ptr(context.window_manager, int(self.source_window_ptr))
        source_area = state._find_area_by_ptr(
            source_window.screen if source_window is not None else None,
            int(self.source_area_ptr),
        )
        if not state.move_area_absolute(
            context.window_manager,
            source_window,
            source_area,
            self.placement,
        ):
            self.report({"ERROR"}, "Floaty could not move this editor to the selected edge")
            return {"CANCELLED"}

        state.tag_redraw_all(context.window_manager)
        return {"FINISHED"}


def _build_place_target_menu(index):
    return type(
        f"FLOATY_MT_place_detached_window_target_{index}",
        (bpy.types.Menu, _FLOATY_MT_place_target_base),
        {
            "bl_idname": f"FLOATY_MT_place_detached_window_target_{index}",
            "bl_label": "Place Editor",
            "target_index": index,
        },
    )


def _build_move_target_menu(index):
    return type(
        f"FLOATY_MT_move_active_editor_target_{index}",
        (bpy.types.Menu, _FLOATY_MT_move_target_base),
        {
            "bl_idname": f"FLOATY_MT_move_active_editor_target_{index}",
            "bl_label": "Move Active Editor",
            "target_index": index,
        },
    )


for _menu_index in range(_MAX_PLACE_TARGET_MENUS):
    globals()[f"FLOATY_MT_place_detached_window_target_{_menu_index}"] = _build_place_target_menu(_menu_index)
    globals()[f"FLOATY_MT_move_active_editor_target_{_menu_index}"] = _build_move_target_menu(_menu_index)


class FLOATY_OT_cleanup_detached_windows(bpy.types.Operator):
    bl_idname = "floaty.cleanup_detached_windows"
    bl_label = "Refresh Detached Windows"
    bl_description = "Remove stale detached-window entries from Floaty tracking"

    def execute(self, context):
        state.cleanup_closed_windows(context.window_manager)
        state.tag_redraw_all(context.window_manager)
        return {"FINISHED"}


class FLOATY_OT_duplicate_area_to_window(bpy.types.Operator):
    bl_idname = "floaty.duplicate_active_editor"
    bl_label = "Duplicate Active Editor"
    bl_description = "Duplicate the current editor into a new Blender window"

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.window is not None and
            not state.is_layout_operation_pending() and
            state.supports_area(context.area.type)
        )

    def execute(self, context):
        before_window_ptrs = {
            window.as_pointer() for window in context.window_manager.windows
        }
        source_window_ptr = context.window.as_pointer()
        source_area_ptr = context.area.as_pointer()
        area_type = context.area.type

        result = bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
        if "FINISHED" in result:
            state.schedule_finalize_detach(
                context.window_manager,
                before_window_ptrs,
                source_window_ptr,
                source_area_ptr,
                area_type,
            )
        return result
