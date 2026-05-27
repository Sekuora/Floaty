import bpy

from .. import properties
from .. import state
from .content import draw_detached_window_list, draw_manager_content


class FLOATY_PT_manager_sidebar(bpy.types.Panel):
    bl_label = "Floaty Detach"
    bl_idname = "FLOATY_PT_manager_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Floaty"

    @classmethod
    def poll(cls, context):
        return properties.should_show_sidebar_panel(context)

    def draw(self, context):
        draw_manager_content(self.layout, context)
        draw_detached_window_list(self.layout, context, state)
        self.layout.operator("floaty.cleanup_detached_windows", text="Refresh Tracking")
