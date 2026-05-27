import json
import time

import bpy

from . import state


def _workspace_name_for_window(window, context=None):
    workspace = getattr(window, "workspace", None)
    if workspace is not None:
        return workspace.name
    if context is not None and getattr(context, "workspace", None) is not None:
        return context.workspace.name
    return ""


def _capture_window_layout_state(window, context=None):
    screen = window.screen
    window_ptr = window.as_pointer()
    detached_info = state._detached_windows.get(window_ptr) or {}
    areas = []

    if screen is not None:
        for area in screen.areas:
            if not state.supports_area(area.type):
                continue
            area_state = state._capture_area_state(area)
            area_state["type"] = area.type
            area_state["label"] = state.area_type_label(area.type)
            areas.append(area_state)

    layout_bounds = _area_state_bounds(areas)

    return {
        "snapshot_window_key": _snapshot_window_key(window_ptr, areas),
        "window_ptr": window_ptr,
        "workspace_name": _workspace_name_for_window(window, context),
        "screen_name": screen.name if screen is not None else "",
        "is_detached": window_ptr in state._detached_windows,
        "detached_area_type": detached_info.get("area_type", ""),
        "detached_source_window_ptr": detached_info.get("source_window_ptr", 0),
        "detached_source_area_state": detached_info.get("source_area_state") or {},
        "areas": areas,
        "layout_bounds": layout_bounds or {},
        "layout_tree": _infer_split_tree(areas, layout_bounds) if layout_bounds else {},
    }


def _snapshot_window_key(_window_ptr, areas):
    area_signature = "|".join(
        f"{area.get('type', '')}:{int(round(float(area.get('x', 0))))},"
        f"{int(round(float(area.get('y', 0))))},"
        f"{int(round(float(area.get('width', 0))))},"
        f"{int(round(float(area.get('height', 0))))}"
        for area in sorted(areas, key=lambda item: (item.get("type", ""), item.get("x", 0), item.get("y", 0)))
    )
    return area_signature


def capture_workspace_snapshot(context, name):
    window_manager = context.window_manager
    state.cleanup_closed_windows(window_manager)

    windows = [
        _capture_window_layout_state(window, context)
        for window in window_manager.windows
    ]
    detached_windows = [window for window in windows if window["is_detached"]]
    workspace_name = _workspace_name_for_window(context.window, context) if context.window else ""
    display_name = (name or "").strip() or workspace_name or "Workspace Snapshot"
    summary = (
        f"{workspace_name or 'No workspace'} | "
        f"{len(windows)} windows, {len(detached_windows)} detached"
    )

    return {
        "version": 2,
        "name": display_name,
        "workspace_name": workspace_name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "active_window_ptr": context.window.as_pointer() if context.window else 0,
        "windows": windows,
    }


def snapshot_to_json(snapshot_data):
    return json.dumps(snapshot_data, separators=(",", ":"), sort_keys=True)


def snapshot_from_json(data_json):
    try:
        return json.loads(data_json or "{}")
    except (TypeError, ValueError):
        return {}


def _saved_window_area_count(saved_window):
    return len(saved_window.get("areas", []))


def _area_state_bounds(area_states):
    if not area_states:
        return None

    min_x = min(float(area.get("x", 0.0)) for area in area_states)
    min_y = min(float(area.get("y", 0.0)) for area in area_states)
    max_x = max(float(area.get("x", 0.0)) + float(area.get("width", 0.0)) for area in area_states)
    max_y = max(float(area.get("y", 0.0)) + float(area.get("height", 0.0)) for area in area_states)
    return {
        "x": min_x,
        "y": min_y,
        "width": max(1.0, max_x - min_x),
        "height": max(1.0, max_y - min_y),
    }


def _split_candidates(area_states, rect, axis):
    if axis == "V":
        rect_min = float(rect["x"])
        rect_max = rect_min + float(rect["width"])
        values = {
            float(area.get("x", 0.0))
            for area in area_states
        } | {
            float(area.get("x", 0.0)) + float(area.get("width", 0.0))
            for area in area_states
        }
    else:
        rect_min = float(rect["y"])
        rect_max = rect_min + float(rect["height"])
        values = {
            float(area.get("y", 0.0))
            for area in area_states
        } | {
            float(area.get("y", 0.0)) + float(area.get("height", 0.0))
            for area in area_states
        }

    return sorted(value for value in values if rect_min + 2.0 < value < rect_max - 2.0)


def _infer_split_tree(area_states, rect):
    node_rect = {
        "x": float(rect["x"]),
        "y": float(rect["y"]),
        "width": max(1.0, float(rect["width"])),
        "height": max(1.0, float(rect["height"])),
    }
    if not area_states:
        return {}
    if len(area_states) == 1:
        return {"rect": node_rect, "leaf": dict(area_states[0])}

    tolerance = 2.0
    rect_x = node_rect["x"]
    rect_y = node_rect["y"]
    rect_width = node_rect["width"]
    rect_height = node_rect["height"]

    for split_x in _split_candidates(area_states, rect, "V"):
        left = [
            area for area in area_states
            if float(area.get("x", 0.0)) + float(area.get("width", 0.0)) <= split_x + tolerance
        ]
        right = [
            area for area in area_states
            if float(area.get("x", 0.0)) >= split_x - tolerance
        ]
        if left and right and len(left) + len(right) == len(area_states):
            left_width = max(1.0, split_x - rect_x)
            right_width = max(1.0, rect_width - left_width)
            return {
                "rect": node_rect,
                "axis": "V",
                "factor": state._clamp_split_factor(left_width / rect_width),
                "left": _infer_split_tree(left, {
                    "x": rect_x,
                    "y": rect_y,
                    "width": left_width,
                    "height": rect_height,
                }),
                "right": _infer_split_tree(right, {
                    "x": split_x,
                    "y": rect_y,
                    "width": right_width,
                    "height": rect_height,
                }),
            }

    for split_y in _split_candidates(area_states, rect, "H"):
        bottom = [
            area for area in area_states
            if float(area.get("y", 0.0)) + float(area.get("height", 0.0)) <= split_y + tolerance
        ]
        top = [
            area for area in area_states
            if float(area.get("y", 0.0)) >= split_y - tolerance
        ]
        if bottom and top and len(bottom) + len(top) == len(area_states):
            bottom_height = max(1.0, split_y - rect_y)
            top_height = max(1.0, rect_height - bottom_height)
            return {
                "rect": node_rect,
                "axis": "H",
                "factor": state._clamp_split_factor(bottom_height / rect_height),
                "bottom": _infer_split_tree(bottom, {
                    "x": rect_x,
                    "y": rect_y,
                    "width": rect_width,
                    "height": bottom_height,
                }),
                "top": _infer_split_tree(top, {
                    "x": rect_x,
                    "y": split_y,
                    "width": rect_width,
                    "height": top_height,
                }),
            }

    largest_area = max(
        area_states,
        key=lambda area: float(area.get("width", 0.0)) * float(area.get("height", 0.0)),
    )
    return {"rect": node_rect, "leaf": dict(largest_area)}


def _live_supported_areas(window):
    if window is None or window.screen is None:
        return []
    return [area for area in window.screen.areas if state.supports_area(area.type)]


def _saved_area_distance(area, saved_area):
    center_x, center_y = state._area_center(area)
    return (
        abs(center_x - float(saved_area.get("center_x", center_x))) +
        abs(center_y - float(saved_area.get("center_y", center_y))) +
        abs(float(area.width) - float(saved_area.get("width", area.width))) +
        abs(float(area.height) - float(saved_area.get("height", area.height)))
    )


def _restore_saved_area_types(window, saved_window):
    used_area_ptrs = set()
    live_areas = sorted(_live_supported_areas(window), key=lambda area: (float(area.y), float(area.x)))
    saved_areas = saved_window.get("areas", [])

    for index, saved_area in enumerate(saved_areas):
        area = state._find_area_by_ptr(window.screen, saved_area.get("area_ptr"))
        if area is None:
            area = state._area_at_point(
                window.screen,
                saved_area.get("center_x", -1),
                saved_area.get("center_y", -1),
            )
        if area is None and live_areas:
            unused = [candidate for candidate in live_areas if candidate.as_pointer() not in used_area_ptrs]
            if unused:
                area = min(unused, key=lambda candidate: _saved_area_distance(candidate, saved_area))
        if area is None and index < len(live_areas):
            area = live_areas[index]
        if area is None or not state.supports_area(area.type) or area.as_pointer() in used_area_ptrs:
            continue

        saved_type = saved_area.get("type", "")
        if saved_type and state.supports_area(saved_type):
            state._restore_area_type(area, saved_type, saved_area.get("ui_type", ""))
            used_area_ptrs.add(area.as_pointer())


def _primary_saved_window(snapshot_data):
    active_window_ptr = snapshot_data.get("active_window_ptr", 0)
    saved_windows = snapshot_data.get("windows", [])
    for saved_window in saved_windows:
        if not saved_window.get("is_detached") and saved_window.get("window_ptr") == active_window_ptr:
            return saved_window
    for saved_window in saved_windows:
        if not saved_window.get("is_detached"):
            return saved_window
    return saved_windows[0] if saved_windows else None


def _close_window(window):
    if window is None:
        return False
    try:
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.window_close()
    except RuntimeError:
        return False
    return "FINISHED" in result


def _detached_snapshot_keys(snapshot_data):
    return {
        saved_window.get("snapshot_window_key", "")
        for saved_window in snapshot_data.get("windows", [])
        if saved_window.get("is_detached")
    }


def _live_window_snapshot_key(window):
    if window is None or window.screen is None:
        return ""
    areas = []
    for area in window.screen.areas:
        if not state.supports_area(area.type):
            continue
        area_state = state._capture_area_state(area)
        area_state["type"] = area.type
        areas.append(area_state)
    return _snapshot_window_key(window.as_pointer(), areas)


def _close_unmatched_detached_windows(context, snapshot_data, matched_windows=None):
    window_manager = context.window_manager
    state.cleanup_closed_windows(window_manager)
    matched_ptrs = {
        window.as_pointer()
        for window in (matched_windows or [])
        if window is not None
    }
    saved_detached_count = sum(
        1 for saved_window in snapshot_data.get("windows", [])
        if saved_window.get("is_detached")
    )
    saved_keys = _detached_snapshot_keys(snapshot_data)
    live_detached = [window for window, _info in state.iter_detached_windows(window_manager)]

    for window in live_detached:
        if window.as_pointer() in matched_ptrs:
            continue
        if _live_window_snapshot_key(window) in saved_keys:
            continue
        if len(live_detached) <= saved_detached_count:
            continue
        _close_window(window)
        live_detached.remove(window)


def _close_area(window, area):
    if window is None or window.screen is None or area is None or len(window.screen.areas) <= 1:
        return False

    region = state._preferred_region_for_area(area)
    override_kwargs = {
        "window": window,
        "area": area,
    }
    if region is not None:
        override_kwargs["region"] = region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_close("INVOKE_DEFAULT")
    except RuntimeError:
        return False
    return "FINISHED" in result


def _close_extra_areas(window, saved_window):
    target_count = _saved_window_area_count(saved_window)
    if target_count <= 0:
        return

    saved_areas = saved_window.get("areas", [])
    for _ in range(32):
        live_areas = _live_supported_areas(window)
        if len(live_areas) <= target_count:
            return

        def _extra_score(area):
            if not saved_areas:
                return 0.0
            return min(_saved_area_distance(area, saved_area) for saved_area in saved_areas)

        area_to_close = max(live_areas, key=_extra_score)
        if not _close_area(window, area_to_close):
            return


def _reset_window_to_single_supported_area(window):
    if window is None or window.screen is None:
        return None

    base_area = state._largest_supported_area(window.screen)
    base_area_ptr = base_area.as_pointer() if base_area is not None else 0

    for _attempt in range(64):
        live_areas = _live_supported_areas(window)
        if len(live_areas) <= 1:
            return live_areas[0] if live_areas else None

        base_area = state._find_area_by_ptr(window.screen, base_area_ptr)
        if base_area is None:
            base_area = state._largest_supported_area(window.screen)
            base_area_ptr = base_area.as_pointer() if base_area is not None else 0

        candidates = [area for area in live_areas if area.as_pointer() != base_area_ptr]
        if not candidates:
            candidates = live_areas[1:]

        closed_any = False
        for area in sorted(candidates, key=lambda item: float(item.width) * float(item.height)):
            if _close_area(window, area):
                closed_any = True
                break

        if not closed_any:
            return base_area

    return state._largest_supported_area(window.screen)


def _area_rect(area):
    return {
        "x": float(area.x),
        "y": float(area.y),
        "width": max(1.0, float(area.width)),
        "height": max(1.0, float(area.height)),
    }


def _center_in_rect(area, rect):
    center_x, center_y = state._area_center(area)
    return (
        float(rect["x"]) - 1.0 <= center_x <= float(rect["x"]) + float(rect["width"]) + 1.0 and
        float(rect["y"]) - 1.0 <= center_y <= float(rect["y"]) + float(rect["height"]) + 1.0
    )


def _execute_restore_split(window, area, node):
    axis = node.get("axis", "V")
    factor = state._clamp_split_factor(float(node.get("factor", 0.5)))
    direction = "VERTICAL" if axis == "V" else "HORIZONTAL"
    area_rect = _area_rect(area)
    before_area_ptrs = {candidate.as_pointer() for candidate in window.screen.areas}
    region = state._preferred_region_for_area(area)
    override_kwargs = {
        "window": window,
        "area": area,
    }
    if region is not None:
        override_kwargs["region"] = region

    cursor_x = int(round(area_rect["x"] + (area_rect["width"] * factor)))
    cursor_y = int(round(area_rect["y"] + (area_rect["height"] * factor)))
    if axis == "V":
        cursor = (cursor_x, int(round(area_rect["y"] + (area_rect["height"] * 0.5))))
    else:
        cursor = (int(round(area_rect["x"] + (area_rect["width"] * 0.5))), cursor_y)

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_split(direction=direction, factor=factor, cursor=cursor)
    except RuntimeError:
        return None

    if "FINISHED" not in result:
        return None

    return {
        "node": node,
        "source_area_ptr": area.as_pointer(),
        "parent_area_rect": area_rect,
        "before_area_ptrs": before_area_ptrs,
        "attempts": 0,
    }


def _restore_split_candidates(window, pending_split):
    area_rect = pending_split["parent_area_rect"]
    before_area_ptrs = pending_split["before_area_ptrs"]
    axis = pending_split["node"].get("axis", "V")
    size_key = "width" if axis == "V" else "height"
    candidates = [
        candidate for candidate in _live_supported_areas(window)
        if (
            _center_in_rect(candidate, area_rect) and
            int(round(float(getattr(candidate, size_key)))) > 0
        )
    ]
    if len(candidates) < 2:
        original_area = state._find_area_by_ptr(window.screen, pending_split.get("source_area_ptr"))
        new_areas = [
            candidate for candidate in _live_supported_areas(window)
            if (
                candidate.as_pointer() not in before_area_ptrs and
                int(round(float(getattr(candidate, size_key)))) > 0
            )
        ]
        candidates = [candidate for candidate in [original_area, *new_areas] if candidate is not None]

    if axis == "V":
        ordered = sorted(candidates, key=lambda item: (float(state._area_center(item)[0]), float(item.x)))
    else:
        ordered = sorted(candidates, key=lambda item: (float(state._area_center(item)[1]), float(item.y)))

    return ordered if len(ordered) >= 2 else []


def _node_rect(node):
    if not node:
        return None
    rect = node.get("rect")
    if rect:
        return rect
    leaf = node.get("leaf")
    if leaf:
        return leaf
    return None


def _normalized_rect_center(rect, parent_rect):
    if not rect or not parent_rect:
        return (0.5, 0.5)
    parent_width = max(1.0, float(parent_rect.get("width", 1.0)))
    parent_height = max(1.0, float(parent_rect.get("height", 1.0)))
    center_x = float(rect.get("x", 0.0)) + (float(rect.get("width", 0.0)) / 2.0)
    center_y = float(rect.get("y", 0.0)) + (float(rect.get("height", 0.0)) / 2.0)
    return (
        (center_x - float(parent_rect.get("x", 0.0))) / parent_width,
        (center_y - float(parent_rect.get("y", 0.0))) / parent_height,
    )


def _normalized_area_center(area, parent_area_rect):
    center_x, center_y = state._area_center(area)
    parent_width = max(1.0, float(parent_area_rect.get("width", 1.0)))
    parent_height = max(1.0, float(parent_area_rect.get("height", 1.0)))
    return (
        (center_x - float(parent_area_rect.get("x", 0.0))) / parent_width,
        (center_y - float(parent_area_rect.get("y", 0.0))) / parent_height,
    )


def _pick_child_area(candidates, parent_area_rect, parent_node_rect, child_node, used_area_ptrs):
    child_rect = _node_rect(child_node)
    expected_x, expected_y = _normalized_rect_center(child_rect, parent_node_rect)
    available = [area for area in candidates if area.as_pointer() not in used_area_ptrs]
    if not available:
        return None

    def _score(area):
        actual_x, actual_y = _normalized_area_center(area, parent_area_rect)
        return abs(actual_x - expected_x) + abs(actual_y - expected_y)

    return min(available, key=_score)


def _assign_child_areas(candidates, parent_area_rect, node):
    parent_node_rect = _node_rect(node)
    if node.get("axis", "V") == "V":
        first_child = node.get("left", {})
        second_child = node.get("right", {})
    else:
        first_child = node.get("bottom", {})
        second_child = node.get("top", {})

    used_area_ptrs = set()
    first_area = _pick_child_area(candidates, parent_area_rect, parent_node_rect, first_child, used_area_ptrs)
    if first_area is not None:
        used_area_ptrs.add(first_area.as_pointer())
    second_area = _pick_child_area(candidates, parent_area_rect, parent_node_rect, second_child, used_area_ptrs)
    return first_area, second_area


def _child_restore_tasks(node, first_area, second_area):
    if node.get("axis", "V") == "V":
        return [
            {"area_ptr": first_area.as_pointer(), "node": node.get("left", {})},
            {"area_ptr": second_area.as_pointer(), "node": node.get("right", {})},
        ]
    return [
        {"area_ptr": first_area.as_pointer(), "node": node.get("bottom", {})},
        {"area_ptr": second_area.as_pointer(), "node": node.get("top", {})},
    ]


def _schedule_restore_split_tree(window_manager, window, area, layout_tree):
    window_ptr = window.as_pointer()
    tasks = [{"area_ptr": area.as_pointer(), "node": layout_tree}]
    pending_split = {"data": None}

    def _restore_next():
        current_window = state._find_window_by_ptr(window_manager, window_ptr)
        if current_window is None or current_window.screen is None:
            return None

        if pending_split["data"] is not None:
            split_data = pending_split["data"]
            candidates = _restore_split_candidates(current_window, split_data)
            first_area, second_area = _assign_child_areas(
                candidates,
                split_data["parent_area_rect"],
                split_data["node"],
            )
            if first_area is None or second_area is None:
                split_data["attempts"] += 1
                if split_data["attempts"] >= 20:
                    pending_split["data"] = None
                    return 0.0
                return 0.05

            pending_split["data"] = None
            tasks.extend(reversed(_child_restore_tasks(split_data["node"], first_area, second_area)))
            return 0.0

        if not tasks:
            state.tag_redraw_all(window_manager)
            return None

        task = tasks.pop()
        node = task.get("node") or {}
        area = state._find_area_by_ptr(current_window.screen, task.get("area_ptr"))
        if area is None:
            return 0.0

        leaf = node.get("leaf")
        if leaf is not None:
            area_type = leaf.get("type", "")
            if area_type and state.supports_area(area_type):
                state._restore_area_type(area, area_type, leaf.get("ui_type", ""))
            return 0.0

        split_data = _execute_restore_split(current_window, area, node)
        if split_data is None:
            return 0.0

        pending_split["data"] = split_data
        return 0.05

    bpy.app.timers.register(_restore_next, first_interval=0.05)
    return True


def _layout_tree_for_saved_window(saved_window):
    layout_tree = saved_window.get("layout_tree") or {}
    if layout_tree and layout_tree.get("rect"):
        return layout_tree

    saved_areas = saved_window.get("areas", [])
    bounds = saved_window.get("layout_bounds") or _area_state_bounds(saved_areas)
    if not saved_areas or not bounds:
        return {}
    return _infer_split_tree(saved_areas, bounds)


def _restore_window_layout(window, saved_window):
    layout_tree = _layout_tree_for_saved_window(saved_window)
    if not layout_tree:
        _restore_saved_area_types(window, saved_window)
        return False

    base_area = _reset_window_to_single_supported_area(window)
    if base_area is None:
        return False

    return _schedule_restore_split_tree(bpy.context.window_manager, window, base_area, layout_tree)


def _recreate_saved_detached_window(window_manager, base_window, saved_window):
    if base_window is None or base_window.screen is None:
        return False

    source_area = state._largest_supported_area(base_window.screen)
    if source_area is None:
        return False

    before_window_ptrs = state.active_window_ptrs(window_manager)
    source_region = state._preferred_region_for_area(source_area)
    override_kwargs = {
        "window": base_window,
        "area": source_area,
    }
    if source_region is not None:
        override_kwargs["region"] = source_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
    except RuntimeError:
        return False

    if "FINISHED" not in result:
        return False

    attempts = {"count": 0}

    def _finalize():
        new_windows = [
            window for window in window_manager.windows
            if window.as_pointer() not in before_window_ptrs
        ]
        if not new_windows:
            attempts["count"] += 1
            if attempts["count"] >= 20:
                return None
            return 0.05

        new_window = new_windows[0]
        area_type = saved_window.get("detached_area_type") or ""
        if not area_type:
            saved_areas = saved_window.get("areas", [])
            area_type = saved_areas[0].get("type", "") if saved_areas else ""

        detached_area = state._largest_supported_area(new_window.screen)
        if detached_area is not None and area_type and state.supports_area(area_type):
            saved_areas = saved_window.get("areas", [])
            saved_ui_type = saved_areas[0].get("ui_type", "") if saved_areas else ""
            state._restore_area_type(detached_area, area_type, saved_ui_type)

        if area_type:
            state.mark_detached_window(
                new_window.as_pointer(),
                base_window.as_pointer(),
                area_type,
                saved_window.get("detached_source_area_state") or {},
            )
        _restore_window_layout(new_window, saved_window)
        state.tag_redraw_all(window_manager)
        return None

    bpy.app.timers.register(_finalize, first_interval=0.05)
    return True


def _best_live_window_for_saved(live_windows, saved_window, used_window_ptrs):
    saved_key = saved_window.get("snapshot_window_key", "")
    saved_area_count = _saved_window_area_count(saved_window)
    candidates = []

    for window in live_windows:
        if window.as_pointer() in used_window_ptrs or window.screen is None:
            continue
        if state.is_detached_window(window):
            continue

        live_area_count = len(_live_supported_areas(window))
        live_key = _live_window_snapshot_key(window)
        candidates.append((
            0 if live_key == saved_key else 1,
            max(0, saved_area_count - live_area_count),
            abs(saved_area_count - live_area_count),
            -live_area_count,
            window,
        ))

    if not candidates:
        return None
    return min(candidates, key=lambda item: item[:4])[-1]


def _match_saved_windows(context, snapshot_data):
    window_manager = context.window_manager
    live_windows = list(window_manager.windows)
    windows_by_ptr = {window.as_pointer(): window for window in live_windows}
    primary_saved = _primary_saved_window(snapshot_data)
    primary_live = None
    matches = {}

    saved_windows = sorted(
        snapshot_data.get("windows", []),
        key=lambda saved_window: (bool(saved_window.get("is_detached")),),
    )

    used_window_ptrs = set()
    for saved_window in saved_windows:
        live_window = windows_by_ptr.get(saved_window.get("window_ptr"))
        if live_window is not None:
            saved_is_detached = bool(saved_window.get("is_detached"))
            if state.is_detached_window(live_window) != saved_is_detached:
                live_window = None
        if (
            live_window is None and
            saved_window is primary_saved and
            not saved_window.get("is_detached")
        ):
            live_window = _best_live_window_for_saved(live_windows, saved_window, used_window_ptrs)
            primary_live = live_window
        if live_window is None and not saved_window.get("is_detached"):
            live_window = _best_live_window_for_saved(live_windows, saved_window, used_window_ptrs)
        if live_window is None and saved_window.get("is_detached"):
            live_detached = [
                window for window, info in state.iter_detached_windows(window_manager)
                if (
                    window.as_pointer() not in used_window_ptrs and
                    info.get("area_type") == saved_window.get("detached_area_type") and
                    len(_live_supported_areas(window)) == _saved_window_area_count(saved_window)
                )
            ]
            if live_detached:
                live_window = live_detached[0]
        if live_window is not None:
            matches[id(saved_window)] = live_window
            used_window_ptrs.add(live_window.as_pointer())
            if saved_window is primary_saved:
                primary_live = live_window

    return matches, primary_saved, primary_live


def _prune_extra_windows(context, snapshot_data, matches):
    window_manager = context.window_manager
    target_window_count = len(snapshot_data.get("windows", []))
    matched_ptrs = {window.as_pointer() for window in matches.values() if window is not None}
    live_windows = list(window_manager.windows)

    for window in live_windows:
        if len(window_manager.windows) <= target_window_count:
            return
        if window.as_pointer() in matched_ptrs or window == context.window:
            continue
        if state.is_detached_window(window) or len(window_manager.windows) > target_window_count:
            _close_window(window)


def restore_workspace_snapshot(context, snapshot_data):
    workspace_name = snapshot_data.get("workspace_name", "")
    if workspace_name and context.window is not None:
        workspace = bpy.data.workspaces.get(workspace_name)
        if workspace is not None:
            context.window.workspace = workspace

    window_manager = context.window_manager
    state.cleanup_closed_windows(window_manager)
    matches, primary_saved_window, primary_live_window = _match_saved_windows(context, snapshot_data)
    _prune_extra_windows(context, snapshot_data, matches)
    matched_restore_windows = []

    for saved_window in snapshot_data.get("windows", []):
        window = matches.get(id(saved_window))
        if window is None or window.screen is None:
            if saved_window.get("is_detached"):
                _recreate_saved_detached_window(window_manager, primary_live_window, saved_window)
            continue
        matched_restore_windows.append(window)

        if saved_window.get("is_detached"):
            area_type = saved_window.get("detached_area_type") or ""
            if area_type:
                state.mark_detached_window(
                    window.as_pointer(),
                    saved_window.get("detached_source_window_ptr", 0),
                    area_type,
                    saved_window.get("detached_source_area_state") or {},
                )

        saved_workspace_name = saved_window.get("workspace_name", "")
        if saved_workspace_name:
            workspace = bpy.data.workspaces.get(saved_workspace_name)
            if workspace is not None:
                window.workspace = workspace

        _restore_window_layout(window, saved_window)

    def _final_prune():
        _close_unmatched_detached_windows(context, snapshot_data, matched_restore_windows)
        state.tag_redraw_all(window_manager)
        return None

    bpy.app.timers.register(_final_prune, first_interval=0.2)
    state.tag_redraw_all(window_manager)
    return True
