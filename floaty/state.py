import json

import bpy
from bpy.app.handlers import persistent


_detached_windows = {}
_closing_window_ptrs = set()
_layout_operation_pending = False
_detached_sync_timer_pending = False
_SCREEN_DETACHED_MARKER_KEY = "floaty_detached_window"
_SCREEN_DETACHED_MARKER_VERSION = 1
_AREA_TYPE_LABELS = {
    "VIEW_3D": "3D Viewport",
    "IMAGE_EDITOR": "Image Editor",
    "UV": "UV Editor",
    "NODE_EDITOR": "Node Editor",
    "SEQUENCE_EDITOR": "Sequencer",
    "CLIP_EDITOR": "Movie Clip Editor",
    "DOPESHEET_EDITOR": "Dope Sheet",
    "GRAPH_EDITOR": "Graph Editor",
    "NLA_EDITOR": "NLA Editor",
    "TEXT_EDITOR": "Text Editor",
    "CONSOLE": "Python Console",
    "INFO": "Info",
    "OUTLINER": "Outliner",
    "PROPERTIES": "Properties",
    "FILE_BROWSER": "File Browser",
    "SPREADSHEET": "Spreadsheet",
    "ASSETS": "Asset Browser",
    "PREFERENCES": "Preferences",
}
_MANUAL_PLACEMENT_SOURCE_SIDE = {
    "TOP": "TOP",
    "BOTTOM": "BOTTOM",
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
}
_MIN_ABSOLUTE_VERTICAL_REMAINDER = 64.0


def supports_area(area_type):
    return area_type not in {"TOPBAR", "STATUSBAR"}


def _log_width_debug(event, **values):
    details = ", ".join(f"{key}={value}" for key, value in values.items())
    print(f"[Floaty][width] {event}: {details}")


def _log_height_debug(event, **values):
    details = ", ".join(f"{key}={value}" for key, value in values.items())
    print(f"[Floaty][height] {event}: {details}")


def _log_action_debug(event, **values):
    details = ", ".join(f"{key}={value}" for key, value in values.items())
    print(f"[Floaty][action] {event}: {details}")


def _format_rect_from_values(x, y, width, height):
    return (
        f"x={int(round(float(x)))},"
        f"y={int(round(float(y)))},"
        f"w={int(round(float(width)))},"
        f"h={int(round(float(height)))}"
    )


def _describe_window(window):
    if window is None:
        return "window=None"
    screen = getattr(window, "screen", None)
    screen_name = screen.name if screen is not None else ""
    return f"window={window.as_pointer()},screen={screen_name}"


def _describe_area(window, area):
    if area is None:
        return f"{_describe_window(window)},area=None"
    ui_type = getattr(area, "ui_type", "")
    return (
        f"{area_type_label(area.type)}({area.type}),"
        f"{_describe_window(window)},"
        f"area={area.as_pointer()},"
        f"ui={ui_type},"
        f"rect=({_format_rect_from_values(area.x, area.y, area.width, area.height)})"
    )


def _describe_area_state(area_type, area_state):
    area_state = area_state or {}
    ui_type = area_state.get("ui_type", "")
    if area_state:
        rect = _format_rect_from_values(
            area_state.get("x", 0),
            area_state.get("y", 0),
            area_state.get("width", 0),
            area_state.get("height", 0),
        )
    else:
        rect = "unknown"
    return f"{area_type_label(area_type)}({area_type}),ui={ui_type},rect=({rect})"


def _describe_detached_window(window, detached_info, live_area_state=None):
    area_type = (detached_info or {}).get("area_type", "")
    area_state = live_area_state or (detached_info or {}).get("source_area_state") or {}
    return f"{_describe_area_state(area_type, area_state)},{_describe_window(window)}"


def _placement_size_key(placement):
    return "width" if placement in {"LEFT", "RIGHT"} else "height"


def is_layout_operation_pending():
    return _layout_operation_pending


def _begin_layout_operation():
    global _layout_operation_pending
    if _layout_operation_pending:
        return False
    _layout_operation_pending = True
    return True


def _end_layout_operation():
    global _layout_operation_pending
    _layout_operation_pending = False


def _detached_marker_payload(info):
    return {
        "version": _SCREEN_DETACHED_MARKER_VERSION,
        "source_window_ptr": _safe_int(info.get("source_window_ptr"), 0),
        "area_type": info.get("area_type", ""),
        "source_area_state": info.get("source_area_state") or {},
    }


def _write_detached_screen_marker(window, info):
    screen = getattr(window, "screen", None)
    if screen is None:
        return
    try:
        screen[_SCREEN_DETACHED_MARKER_KEY] = json.dumps(
            _detached_marker_payload(info),
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        screen[_SCREEN_DETACHED_MARKER_KEY] = json.dumps(
            _detached_marker_payload({
                "source_window_ptr": info.get("source_window_ptr", 0),
                "area_type": info.get("area_type", ""),
                "source_area_state": {},
            }),
            separators=(",", ":"),
            sort_keys=True,
        )


def _clear_detached_screen_marker(window):
    screen = getattr(window, "screen", None)
    if screen is None:
        return
    try:
        if _SCREEN_DETACHED_MARKER_KEY in screen:
            del screen[_SCREEN_DETACHED_MARKER_KEY]
    except TypeError:
        pass


def _clear_detached_screen_marker_by_ptr(screen_ptr):
    if not screen_ptr:
        return
    for screen in bpy.data.screens:
        if screen.as_pointer() != screen_ptr:
            continue
        try:
            if _SCREEN_DETACHED_MARKER_KEY in screen:
                del screen[_SCREEN_DETACHED_MARKER_KEY]
        except TypeError:
            pass
        return


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _detached_info_from_screen_marker(window, window_manager):
    screen = getattr(window, "screen", None)
    if screen is None:
        return None

    raw_marker = screen.get(_SCREEN_DETACHED_MARKER_KEY)
    if not raw_marker:
        return None

    try:
        marker = json.loads(raw_marker) if isinstance(raw_marker, str) else dict(raw_marker)
    except (TypeError, ValueError):
        return None

    area_type = marker.get("area_type", "")
    if not area_type:
        detached_area = _largest_supported_area(screen)
        area_type = detached_area.type if detached_area is not None else ""
    if not area_type or not supports_area(area_type):
        return None

    source_area_state = marker.get("source_area_state") or {}
    if not isinstance(source_area_state, dict):
        source_area_state = {}

    source_window_ptr = _safe_int(marker.get("source_window_ptr"), 0)
    if source_window_ptr and _find_window_by_ptr(window_manager, source_window_ptr) is None:
        source_window_ptr = 0

    return {
        "source_window_ptr": source_window_ptr,
        "area_type": area_type,
        "source_area_state": source_area_state,
    }


def _sync_detached_screen_markers(window_manager):
    if window_manager is None:
        return

    live_windows = list(window_manager.windows)
    detached_screen_ptrs = set()

    for window in live_windows:
        window_ptr = window.as_pointer()
        screen = getattr(window, "screen", None)
        if screen is None:
            continue

        info = _detached_windows.get(window_ptr)
        if info is not None:
            info["screen_ptr"] = screen.as_pointer()
            _write_detached_screen_marker(window, info)
            detached_screen_ptrs.add(screen.as_pointer())
            continue

        marker_info = _detached_info_from_screen_marker(window, window_manager)
        if marker_info is None:
            continue

        if window_ptr in _closing_window_ptrs:
            _clear_detached_screen_marker(window)
            continue

        marker_info["screen_ptr"] = screen.as_pointer()
        _detached_windows[window_ptr] = marker_info
        detached_screen_ptrs.add(screen.as_pointer())

    for window in live_windows:
        screen = getattr(window, "screen", None)
        if screen is None or screen.as_pointer() in detached_screen_ptrs:
            continue
        if window.as_pointer() not in _detached_windows:
            _clear_detached_screen_marker(window)


def cleanup_closed_windows(window_manager):
    if window_manager is None:
        return
    live_window_ptrs = {window.as_pointer() for window in window_manager.windows}
    stale_ptrs = [ptr for ptr in _detached_windows if ptr not in live_window_ptrs]
    for ptr in stale_ptrs:
        info = _detached_windows.pop(ptr, None)
        if info is not None:
            _clear_detached_screen_marker_by_ptr(info.get("screen_ptr", 0))
    _closing_window_ptrs.intersection_update(live_window_ptrs)
    _sync_detached_screen_markers(window_manager)


def is_detached_window(window):
    if window is None:
        return False
    cleanup_closed_windows(bpy.context.window_manager)
    return window.as_pointer() in _detached_windows


def mark_detached_window(window_ptr, source_window_ptr, area_type, source_area_state):
    info = {
        "source_window_ptr": source_window_ptr,
        "area_type": area_type,
        "source_area_state": source_area_state,
    }
    _detached_windows[window_ptr] = info

    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is not None:
        window = _find_window_by_ptr(window_manager, window_ptr)
        if window is not None:
            screen = getattr(window, "screen", None)
            if screen is not None:
                info["screen_ptr"] = screen.as_pointer()
            _write_detached_screen_marker(window, info)


def unmark_detached_window(window):
    if window is None:
        return
    _detached_windows.pop(window.as_pointer(), None)
    _clear_detached_screen_marker(window)


def retire_detached_window(window):
    if window is None:
        return
    window_ptr = window.as_pointer()
    _detached_windows.pop(window_ptr, None)
    _clear_detached_screen_marker(window)
    _closing_window_ptrs.add(window_ptr)


def active_window_ptrs(window_manager):
    cleanup_closed_windows(window_manager)
    return {
        window.as_pointer()
        for window in window_manager.windows
        if window.as_pointer() not in _closing_window_ptrs
    }


def iter_detached_windows(window_manager):
    cleanup_closed_windows(window_manager)
    windows_by_ptr = {window.as_pointer(): window for window in window_manager.windows}
    for window_ptr, info in sorted(_detached_windows.items()):
        window = windows_by_ptr.get(window_ptr)
        if window is None:
            continue
        yield window, info


def area_type_label(area_type):
    return _AREA_TYPE_LABELS.get(area_type, area_type.replace("_", " ").title())


def iter_placeable_areas(window_manager, detached_window=None):
    cleanup_closed_windows(window_manager)
    detached_ptrs = set(_detached_windows)
    detached_window_ptr = detached_window.as_pointer() if detached_window is not None else None
    counts_by_label = {}

    for window in window_manager.windows:
        window_ptr = window.as_pointer()
        if (
            window_ptr == detached_window_ptr or
            window_ptr in detached_ptrs or
            window_ptr in _closing_window_ptrs
        ):
            continue

        screen = window.screen
        if screen is None:
            continue

        for area in screen.areas:
            if not supports_area(area.type):
                continue

            label_root = area_type_label(area.type)
            counts_by_label[label_root] = counts_by_label.get(label_root, 0) + 1

            yield {
                "window": window,
                "area": area,
                "label": f"{label_root} {counts_by_label[label_root]}",
            }


def has_placeable_areas(window_manager, detached_window=None):
    return next(iter_placeable_areas(window_manager, detached_window), None) is not None


def _screen_area_bounds(screen):
    supported_areas = [area for area in screen.areas if supports_area(area.type)]
    if not supported_areas:
        return None

    min_x = min(float(area.x) for area in supported_areas)
    min_y = min(float(area.y) for area in supported_areas)
    max_x = max(float(area.x + area.width) for area in supported_areas)
    max_y = max(float(area.y + area.height) for area in supported_areas)
    return {
        "x": min_x,
        "y": min_y,
        "width": max(1.0, max_x - min_x),
        "height": max(1.0, max_y - min_y),
    }


def _area_touches_screen_edge(area, screen_bounds, placement):
    if placement == "LEFT":
        return int(round(float(area.x))) == int(round(float(screen_bounds["x"])))
    if placement == "RIGHT":
        area_right = float(area.x + area.width)
        screen_right = float(screen_bounds["x"] + screen_bounds["width"])
        return int(round(area_right)) == int(round(screen_right))
    if placement == "TOP":
        area_top = float(area.y + area.height)
        screen_top = float(screen_bounds["y"] + screen_bounds["height"])
        return int(round(area_top)) == int(round(screen_top))
    if placement == "BOTTOM":
        return int(round(float(area.y))) == int(round(float(screen_bounds["y"])))
    return False


def _edge_coverage(area, screen_bounds, placement):
    if placement in {"LEFT", "RIGHT"}:
        return float(area.height) / max(1.0, float(screen_bounds["height"]))
    if placement in {"TOP", "BOTTOM"}:
        return float(area.width) / max(1.0, float(screen_bounds["width"]))
    return 0.0


def _absolute_target_sort_key(target, placement):
    area = target["area"]
    screen_bounds = target["screen_bounds"]
    coverage = _edge_coverage(area, screen_bounds, placement)
    area_size = float(area.width) * float(area.height)
    return (-coverage, -area_size, float(area.x), float(area.y))


def _find_absolute_place_target(window_manager, detached_window, placement):
    edge_targets = []
    for target in iter_placeable_areas(window_manager, detached_window):
        screen_bounds = _screen_area_bounds(target["window"].screen)
        if screen_bounds is None:
            continue

        if not _area_touches_screen_edge(target["area"], screen_bounds, placement):
            continue

        target = dict(target)
        target["screen_bounds"] = screen_bounds
        edge_targets.append(target)

    if not edge_targets:
        return None

    return min(edge_targets, key=lambda target: _absolute_target_sort_key(target, placement))


def _areas_touching_screen_edge(screen, screen_bounds, placement):
    edge_areas = [
        area
        for area in screen.areas
        if (
            supports_area(area.type) and
            _area_touches_screen_edge(area, screen_bounds, placement)
        )
    ]

    if placement in {"LEFT", "RIGHT"}:
        return sorted(edge_areas, key=lambda area: (float(area.y), float(area.x)))
    return sorted(edge_areas, key=lambda area: (float(area.x), float(area.y)))


def _find_window_by_ptr(window_manager, window_ptr):
    for window in window_manager.windows:
        if window.as_pointer() == window_ptr:
            return window
    return None


def _first_placeable_window(window_manager):
    for window in window_manager.windows:
        if (
            window.as_pointer() in _detached_windows or
            window.as_pointer() in _closing_window_ptrs or
            window.screen is None
        ):
            continue
        return window
    return None


def _find_area_by_ptr(screen, area_ptr):
    if screen is None:
        return None
    for area in screen.areas:
        if area.as_pointer() == area_ptr:
            return area
    return None


def _preferred_region_for_area(area):
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return area.regions[0] if area.regions else None


def _capture_area_state(area):
    return {
        "area_ptr": area.as_pointer(),
        "x": area.x,
        "y": area.y,
        "width": area.width,
        "height": area.height,
        "center_x": area.x + (area.width / 2.0),
        "center_y": area.y + (area.height / 2.0),
        "ui_type": getattr(area, "ui_type", ""),
    }


def _capture_rect_from_area_state(area_state):
    return {
        "x": area_state["x"],
        "y": area_state["y"],
        "width": area_state["width"],
        "height": area_state["height"],
    }


def _largest_area(screen):
    if screen is None or not screen.areas:
        return None
    return max(screen.areas, key=lambda area: area.width * area.height)


def _largest_supported_area(screen):
    if screen is None:
        return None
    supported_areas = [area for area in screen.areas if supports_area(area.type)]
    if not supported_areas:
        return None
    return max(supported_areas, key=lambda area: area.width * area.height)


def _area_at_point(screen, x, y):
    if screen is None:
        return None
    for area in screen.areas:
        if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
            return area
    return None


def _point_in_rect(x, y, rect):
    return (
        rect["x"] <= x < rect["x"] + rect["width"] and
        rect["y"] <= y < rect["y"] + rect["height"]
    )


def _capture_rect(area):
    return {
        "x": area.x,
        "y": area.y,
        "width": area.width,
        "height": area.height,
    }


def _area_center(area):
    return (
        area.x + (area.width / 2.0),
        area.y + (area.height / 2.0),
    )


def _rect_center(rect):
    return (
        rect["x"] + (rect["width"] / 2.0),
        rect["y"] + (rect["height"] / 2.0),
    )


def _areas_with_centers_in_rect(screen, rect):
    matches = []
    for area in screen.areas:
        center_x, center_y = _area_center(area)
        if _point_in_rect(center_x, center_y, rect):
            matches.append(area)
    return matches


def _range_overlap(start_a, end_a, start_b, end_b):
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _clamp_split_factor(factor):
    return max(0.05, min(0.95, factor))


def _combine_rects(rect_a, rect_b):
    min_x = min(rect_a["x"], rect_b["x"])
    min_y = min(rect_a["y"], rect_b["y"])
    max_x = max(rect_a["x"] + rect_a["width"], rect_b["x"] + rect_b["width"])
    max_y = max(rect_a["y"] + rect_a["height"], rect_b["y"] + rect_b["height"])
    return {
        "x": min_x,
        "y": min_y,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def _find_absorbing_neighbor(screen, source_area):
    if screen is None or source_area is None:
        return None

    source_rect = _capture_rect(source_area)
    best_match = None
    best_score = -1

    for area in screen.areas:
        if area.as_pointer() == source_area.as_pointer():
            continue

        target_rect = _capture_rect(area)
        side = None
        score = 0

        if source_rect["x"] + source_rect["width"] == target_rect["x"]:
            overlap = _range_overlap(
                source_rect["y"],
                source_rect["y"] + source_rect["height"],
                target_rect["y"],
                target_rect["y"] + target_rect["height"],
            )
            if overlap > 0:
                side = "LEFT"
                score = overlap
        elif target_rect["x"] + target_rect["width"] == source_rect["x"]:
            overlap = _range_overlap(
                source_rect["y"],
                source_rect["y"] + source_rect["height"],
                target_rect["y"],
                target_rect["y"] + target_rect["height"],
            )
            if overlap > 0:
                side = "RIGHT"
                score = overlap
        elif source_rect["y"] + source_rect["height"] == target_rect["y"]:
            overlap = _range_overlap(
                source_rect["x"],
                source_rect["x"] + source_rect["width"],
                target_rect["x"],
                target_rect["x"] + target_rect["width"],
            )
            if overlap > 0:
                side = "BOTTOM"
                score = overlap
        elif target_rect["y"] + target_rect["height"] == source_rect["y"]:
            overlap = _range_overlap(
                source_rect["x"],
                source_rect["x"] + source_rect["width"],
                target_rect["x"],
                target_rect["x"] + target_rect["width"],
            )
            if overlap > 0:
                side = "TOP"
                score = overlap

        if side is None or score <= 0:
            continue

        if score > best_score:
            best_match = {
                "source_side": side,
                "target_area_state": _capture_area_state(area),
                "combined_rect": _combine_rects(source_rect, target_rect),
            }
            best_score = score

    return best_match


def _find_return_target_area(screen, source_area_state):
    if not source_area_state:
        return _largest_area(screen)

    target_state = source_area_state.get("target_area_state") or {}
    target_area = _find_area_by_ptr(screen, target_state.get("area_ptr"))
    if target_area is not None:
        return target_area

    if target_state:
        target_area = _area_at_point(
            screen,
            target_state["center_x"],
            target_state["center_y"],
        )
        if target_area is not None:
            return target_area

    combined_rect = source_area_state.get("combined_rect")
    if combined_rect:
        center_x, center_y = _rect_center(combined_rect)
        target_area = _area_at_point(screen, center_x, center_y)
        if target_area is not None:
            return target_area

    target_area = _area_at_point(
        screen,
        source_area_state["center_x"],
        source_area_state["center_y"],
    )
    if target_area is not None:
        return target_area
    return _largest_area(screen)


def _compute_split_geometry(target_area, source_area_state):
    if not source_area_state:
        target_x = float(target_area.x)
        target_y = float(target_area.y)
        target_width = max(1.0, float(target_area.width))
        target_height = max(1.0, float(target_area.height))
        return {
            "direction": "VERTICAL" if target_width >= target_height else "HORIZONTAL",
            "factor": 0.5,
            "cursor": (
                int(round(target_x + (target_width * 0.5))),
                int(round(target_y + (target_height * 0.5))),
            ),
        }

    combined_rect = source_area_state.get("combined_rect")
    source_side = source_area_state.get("source_side")
    if not combined_rect or not source_side:
        target_x = float(target_area.x)
        target_y = float(target_area.y)
        target_width = max(1.0, float(target_area.width))
        target_height = max(1.0, float(target_area.height))
        return {
            "direction": "VERTICAL" if target_width >= target_height else "HORIZONTAL",
            "factor": 0.5,
            "source_side": "RIGHT",
            "cursor": (
                int(round(target_x + (target_width * 0.5))),
                int(round(target_y + (target_height * 0.5))),
            ),
        }

    source_rect = _capture_rect_from_area_state(source_area_state)
    combined_x = float(combined_rect["x"])
    combined_y = float(combined_rect["y"])
    combined_width = max(1.0, float(combined_rect["width"]))
    combined_height = max(1.0, float(combined_rect["height"]))

    if source_side == "TOP":
        boundary_y = float(source_rect["y"])
        factor = max(0.05, min(0.95, (boundary_y - combined_y) / combined_height))
        return {
            "direction": "HORIZONTAL",
            "factor": factor,
            "source_side": source_side,
            "cursor": (
                int(round(source_area_state["center_x"])),
                int(round(combined_y + (factor * combined_height))),
            ),
        }

    if source_side == "BOTTOM":
        boundary_y = float(source_rect["y"] + source_rect["height"])
        factor = max(0.05, min(0.95, (boundary_y - combined_y) / combined_height))
        return {
            "direction": "HORIZONTAL",
            "factor": factor,
            "source_side": source_side,
            "cursor": (
                int(round(source_area_state["center_x"])),
                int(round(combined_y + (factor * combined_height))),
            ),
        }

    if source_side == "LEFT":
        boundary_x = float(source_rect["x"] + source_rect["width"])
        factor = max(0.05, min(0.95, (boundary_x - combined_x) / combined_width))
        return {
            "direction": "VERTICAL",
            "factor": factor,
            "source_side": source_side,
            "cursor": (
                int(round(combined_x + (factor * combined_width))),
                int(round(source_area_state["center_y"])),
            ),
        }

    boundary_x = float(source_rect["x"])
    factor = max(0.05, min(0.95, (boundary_x - combined_x) / combined_width))
    return {
        "direction": "VERTICAL",
        "factor": factor,
        "source_side": "RIGHT",
        "cursor": (
            int(round(combined_x + (factor * combined_width))),
            int(round(source_area_state["center_y"])),
        ),
    }


def _compute_manual_split_geometry(target_area, source_area_state, placement):
    target_x = float(target_area.x)
    target_y = float(target_area.y)
    target_width = max(1.0, float(target_area.width))
    target_height = max(1.0, float(target_area.height))

    if placement in {"TOP", "BOTTOM"}:
        source_size = max(1.0, float((source_area_state or {}).get("height", target_height)))
        # Manual placement splits only the current target area, so the detached editor
        # should claim a fraction of that existing height directly.
        source_ratio = _clamp_split_factor(source_size / target_height)
        if placement == "TOP":
            factor = _clamp_split_factor(1.0 - source_ratio)
        else:
            factor = source_ratio

        _log_height_debug(
            "manual_split_geometry",
            placement=placement,
            target_height=int(round(target_height)),
            detached_height=int(round(source_size)),
            source_ratio=round(source_ratio, 4),
            factor=round(factor, 4),
            source_side=_MANUAL_PLACEMENT_SOURCE_SIDE[placement],
        )

        return {
            "direction": "HORIZONTAL",
            "factor": factor,
            "source_side": _MANUAL_PLACEMENT_SOURCE_SIDE[placement],
            "cursor": (
                int(round(target_x + (target_width * 0.5))),
                int(round(target_y + (target_height * factor))),
            ),
        }

    source_size = max(1.0, float((source_area_state or {}).get("width", target_width)))
    # Same for width: the detached editor should take its share from the
    # selected editor's current width, not from an imagined combined width.
    source_ratio = _clamp_split_factor(source_size / target_width)
    if placement == "LEFT":
        factor = source_ratio
    else:
        factor = _clamp_split_factor(1.0 - source_ratio)

    _log_width_debug(
        "manual_split_geometry",
        placement=placement,
        target_width=int(round(target_width)),
        detached_width=int(round(source_size)),
        source_ratio=round(source_ratio, 4),
        factor=round(factor, 4),
        source_side=_MANUAL_PLACEMENT_SOURCE_SIDE[placement],
    )

    return {
        "direction": "VERTICAL",
        "factor": factor,
        "source_side": _MANUAL_PLACEMENT_SOURCE_SIDE[placement],
        "cursor": (
            int(round(target_x + (target_width * factor))),
            int(round(target_y + (target_height * 0.5))),
        ),
    }


def _area_state_for_absolute_placement(source_area_state, screen_bounds, placement):
    absolute_state = dict(source_area_state or {})
    if not absolute_state or not screen_bounds:
        return absolute_state

    source_width = max(1.0, float(absolute_state.get("width", 1.0)))
    source_height = max(1.0, float(absolute_state.get("height", 1.0)))

    if placement in {"TOP", "BOTTOM"} and source_height > source_width:
        max_height = max(96.0, float(screen_bounds.get("height", source_height)) * 0.30)
        absolute_state["height"] = min(source_height, source_width, max_height)
    elif placement in {"LEFT", "RIGHT"} and source_width > source_height:
        max_width = max(120.0, float(screen_bounds.get("width", source_width)) * 0.30)
        absolute_state["width"] = min(source_width, source_height, max_width)

    return absolute_state


def _area_state_for_absolute_edge_areas(source_area_state, edge_areas, placement):
    absolute_state = dict(source_area_state or {})
    if not absolute_state or not edge_areas:
        return absolute_state

    if placement in {"TOP", "BOTTOM"}:
        shortest_edge_height = min(max(1.0, float(area.height)) for area in edge_areas)
        minimum_remainder = min(
            _MIN_ABSOLUTE_VERTICAL_REMAINDER,
            shortest_edge_height * 0.35,
        )
        max_strip_height = max(1.0, shortest_edge_height - minimum_remainder)
        absolute_state["height"] = min(
            max(1.0, float(absolute_state.get("height", max_strip_height))),
            max(1.0, max_strip_height),
        )
    else:
        max_strip_width = min(max(1.0, float(area.width)) for area in edge_areas) * 0.95
        absolute_state["width"] = min(
            max(1.0, float(absolute_state.get("width", max_strip_width))),
            max(1.0, max_strip_width),
        )

    return absolute_state


def _capture_detached_window_area_state(detached_window, fallback_state=None):
    detached_area_state = dict(fallback_state or {})
    if detached_window is None or detached_window.screen is None:
        return detached_area_state

    detached_area = _largest_supported_area(detached_window.screen)
    if detached_area is None:
        return detached_area_state

    live_area_state = _capture_area_state(detached_area)
    if detached_area_state.get("ui_type") and not live_area_state.get("ui_type"):
        live_area_state["ui_type"] = detached_area_state["ui_type"]
    if detached_area_state:
        _log_width_debug(
            "detached_live_area",
            captured_width=int(round(float(detached_area_state.get("width", 0.0)))),
            live_width=int(round(float(live_area_state.get("width", 0.0)))),
            area_type=getattr(detached_area, "type", ""),
        )
        _log_height_debug(
            "detached_live_area",
            captured_height=int(round(float(detached_area_state.get("height", 0.0)))),
            live_height=int(round(float(live_area_state.get("height", 0.0)))),
            area_type=getattr(detached_area, "type", ""),
        )
    return live_area_state


def _restore_area_type(area, area_type, ui_type):
    area.type = area_type
    if ui_type:
        try:
            area.ui_type = ui_type
        except (AttributeError, TypeError, ValueError):
            pass


def _pick_area_on_source_side(candidates, source_side):
    if not candidates:
        return None

    if source_side == "TOP":
        return max(candidates, key=lambda area: (area.y, area.height))
    if source_side == "BOTTOM":
        return min(candidates, key=lambda area: (area.y, area.height))
    if source_side == "LEFT":
        return min(candidates, key=lambda area: (area.x, area.width))
    if source_side == "RIGHT":
        return max(candidates, key=lambda area: (area.x, area.width))
    return candidates[0]


def _area_center_is_on_rect_side(area, rect, side):
    center_x, center_y = _area_center(area)
    rect_center_x, rect_center_y = _rect_center(rect)

    if side == "TOP":
        return center_y >= rect_center_y
    if side == "BOTTOM":
        return center_y <= rect_center_y
    if side == "LEFT":
        return center_x <= rect_center_x
    if side == "RIGHT":
        return center_x >= rect_center_x
    return True


def _area_center_is_in_rect(area, rect):
    center_x, center_y = _area_center(area)
    return _point_in_rect(center_x, center_y, rect)


def _pick_area_matching_detached_size(candidates, desired_area_state, placement, fallback_side=None):
    if not candidates:
        return None

    preferred_area = _pick_area_on_source_side(candidates, fallback_side)
    desired_width = max(1.0, float((desired_area_state or {}).get("width", 1.0)))
    desired_height = max(1.0, float((desired_area_state or {}).get("height", 1.0)))

    def _sort_key(area):
        primary_delta = abs(float(area.height) - desired_height)
        secondary_delta = abs(float(area.width) - desired_width)
        if placement in {"LEFT", "RIGHT"}:
            primary_delta, secondary_delta = secondary_delta, primary_delta

        preferred_penalty = 0
        if preferred_area is not None and area.as_pointer() != preferred_area.as_pointer():
            preferred_penalty = 1

        return (
            primary_delta,
            secondary_delta,
            preferred_penalty,
            abs(float(area.width) - desired_width) + abs(float(area.height) - desired_height),
        )

    return min(candidates, key=_sort_key)


def _pick_manual_split_area(candidates, new_areas, source_area_state, target_rect, placement, source_side):
    ready_new_areas = [
        area
        for area in new_areas
        if int(round(float(getattr(area, _placement_size_key(placement))))) > 0
    ]

    if placement in {"TOP", "BOTTOM"}:
        side_candidate_areas = [
            area for area in candidates
            if _area_center_is_on_rect_side(area, target_rect, placement)
        ]
        recreated_area = _pick_area_matching_detached_size(
            side_candidate_areas,
            source_area_state,
            placement,
            source_side,
        )
        if recreated_area is None:
            recreated_area = _pick_area_matching_detached_size(
                candidates,
                source_area_state,
                placement,
                source_side,
            )
        if recreated_area is None:
            recreated_area = _pick_area_matching_detached_size(
                ready_new_areas,
                source_area_state,
                placement,
                source_side,
            )
        return recreated_area

    recreated_area = _pick_area_on_source_side(candidates, source_side)
    if recreated_area is None:
        recreated_area = _pick_area_on_source_side(ready_new_areas, source_side)
    return recreated_area


def _pick_absolute_split_area(candidates, new_areas, target_rect, placement):
    ready_new_areas = [
        area
        for area in new_areas
        if (
            int(round(float(getattr(area, _placement_size_key(placement))))) > 0 and
            _area_center_is_in_rect(area, target_rect)
        )
    ]
    side_candidate_areas = [
        area for area in candidates
        if _area_center_is_on_rect_side(area, target_rect, placement)
    ]
    side_new_areas = [
        area for area in ready_new_areas
        if _area_center_is_on_rect_side(area, target_rect, placement)
    ]

    return (
        _pick_area_on_source_side(side_candidate_areas, placement) or
        _pick_area_on_source_side(side_new_areas, placement) or
        _pick_area_on_source_side(candidates, placement)
    )


def _join_area_into_area(window, screen, area_to_join, target_area):
    if (
        window is None or
        screen is None or
        area_to_join is None or
        target_area is None or
        area_to_join.as_pointer() == target_area.as_pointer()
    ):
        return None

    combined_rect = _combine_rects(_capture_rect(area_to_join), _capture_rect(target_area))
    source_x, source_y = _area_center(area_to_join)
    target_x, target_y = _area_center(target_area)
    source_region = _preferred_region_for_area(area_to_join)
    override_kwargs = {
        "window": window,
        "screen": screen,
        "area": area_to_join,
    }
    if source_region is not None:
        override_kwargs["region"] = source_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_join(
                source_xy=(int(round(source_x)), int(round(source_y))),
                target_xy=(int(round(target_x)), int(round(target_y))),
            )
    except RuntimeError as error:
        _log_width_debug("place_absolute_join_failed", reason=repr(error))
        return None

    if "FINISHED" not in result:
        _log_width_debug("place_absolute_join_failed", reason=result)
        return None

    center_x, center_y = _rect_center(combined_rect)
    joined_area = _area_at_point(screen, center_x, center_y)
    return joined_area


def _schedule_restore_absolute_area(
    window_manager,
    target_window_ptr,
    final_rect,
    area_type,
    ui_type,
    placement,
    strip_count,
    source_window_ptr_to_close=None,
    source_area_ptr_to_close=None,
    action_name="place_absolute",
):
    attempts = {"count": 0}

    def _restore():
        target_window = _find_window_by_ptr(window_manager, target_window_ptr)
        if target_window is None or target_window.screen is None:
            _end_layout_operation()
            return None

        screen = target_window.screen
        center_x, center_y = _rect_center(final_rect)
        final_area = _area_at_point(screen, center_x, center_y)
        if final_area is None:
            attempts["count"] += 1
            if attempts["count"] >= 20:
                _log_action_debug(
                    "attach_failed",
                    action=action_name,
                    placement=placement,
                    reason="final_area_missing",
                    final_rect=f"({_format_rect_from_values(final_rect['x'], final_rect['y'], final_rect['width'], final_rect['height'])})",
                )
                _end_layout_operation()
                return None
            return 0.05

        _restore_area_type(final_area, area_type, ui_type)
        _log_action_debug(
            "attached",
            action=action_name,
            placement=placement,
            editor=area_type_label(area_type),
            attached_as=_describe_area(target_window, final_area),
            strips=strip_count,
            closed_source_window=source_window_ptr_to_close or "",
            closed_source_area=source_area_ptr_to_close or "",
        )
        if (
            source_window_ptr_to_close is not None and
            source_area_ptr_to_close is not None and
            final_area.as_pointer() != source_area_ptr_to_close
        ):
            def _finish_after_close():
                tag_redraw_all(window_manager)
                _end_layout_operation()

            _schedule_close_source_area(
                window_manager,
                source_window_ptr_to_close,
                source_area_ptr_to_close,
                _finish_after_close,
            )
            return None

        if placement in {"LEFT", "RIGHT"}:
            _log_width_debug(
                "place_absolute_selected",
                placement=placement,
                strips=strip_count,
                selected_width=int(round(float(final_area.width))),
                selected_height=int(round(float(final_area.height))),
            )
        else:
            _log_height_debug(
                "place_absolute_selected",
                placement=placement,
                strips=strip_count,
                selected_width=int(round(float(final_area.width))),
                selected_height=int(round(float(final_area.height))),
            )

        tag_redraw_all(window_manager)
        _end_layout_operation()
        return None

    bpy.app.timers.register(_restore, first_interval=0.05)


def _schedule_finalize_absolute_place(
    window_manager,
    target_window_ptr,
    split_records,
    source_area_state,
    area_type,
    ui_type,
    placement,
    source_window_ptr_to_close=None,
    source_area_ptr_to_close=None,
    action_name="place_absolute",
):
    attempts = {"count": 0}
    source_area_ptr_for_close = {"value": source_area_ptr_to_close}

    def _finalize():
        target_window = _find_window_by_ptr(window_manager, target_window_ptr)
        if target_window is None or target_window.screen is None:
            _end_layout_operation()
            return None

        screen = target_window.screen
        strip_areas = []
        for record in split_records:
            target_rect = record["target_rect"]
            before_area_ptrs = record["before_area_ptrs"]
            candidate_areas = _areas_with_centers_in_rect(screen, target_rect)
            new_areas = [
                area for area in screen.areas
                if area.as_pointer() not in before_area_ptrs
            ]
            size_key = _placement_size_key(placement)
            target_size = int(round(float(target_rect[size_key])))
            stale_split = len(candidate_areas) < 2
            stale_single_candidate = (
                len(candidate_areas) == 1 and
                len(new_areas) == 0 and
                int(round(float(getattr(candidate_areas[0], size_key)))) == target_size
            )
            if stale_split or stale_single_candidate:
                attempts["count"] += 1
                if attempts["count"] >= 20:
                    _log_action_debug(
                        "attach_failed",
                        action=action_name,
                        placement=placement,
                        reason="split_stale",
                        target_rect=f"({_format_rect_from_values(target_rect['x'], target_rect['y'], target_rect['width'], target_rect['height'])})",
                    )
                    _end_layout_operation()
                    return None
                return 0.05

            strip_area = _pick_absolute_split_area(
                candidate_areas,
                new_areas,
                target_rect,
                placement,
            )
            if strip_area is None:
                attempts["count"] += 1
                if attempts["count"] >= 20:
                    _log_action_debug(
                        "attach_failed",
                        action=action_name,
                        placement=placement,
                        reason="strip_area_missing",
                        target_rect=f"({_format_rect_from_values(target_rect['x'], target_rect['y'], target_rect['width'], target_rect['height'])})",
                    )
                    _end_layout_operation()
                    return None
                return 0.05

            for candidate_area in candidate_areas:
                if candidate_area.as_pointer() != strip_area.as_pointer():
                    _restore_area_type(
                        candidate_area,
                        record.get("target_area_type", candidate_area.type),
                        record.get("target_ui_type", ""),
                    )

            if (
                placement in {"TOP", "BOTTOM"} and
                source_area_ptr_to_close is not None and
                record.get("split_area_ptr") == source_area_ptr_to_close and
                strip_area.as_pointer() == source_area_ptr_to_close
            ):
                non_strip_areas = [
                    area
                    for area in candidate_areas
                    if area.as_pointer() != strip_area.as_pointer()
                ]
                if non_strip_areas:
                    source_area_ptr_for_close["value"] = non_strip_areas[0].as_pointer()

            if strip_area.as_pointer() not in {area.as_pointer() for area in strip_areas}:
                strip_areas.append(strip_area)

        if not strip_areas:
            _end_layout_operation()
            return None

        if placement in {"LEFT", "RIGHT"}:
            strip_areas.sort(key=lambda area: (float(area.y), float(area.x)))
        else:
            strip_areas.sort(key=lambda area: (float(area.x), float(area.y)))

        joined_area = strip_areas[0]
        final_rect = _capture_rect(joined_area)
        for strip_area in strip_areas[1:]:
            final_rect = _combine_rects(final_rect, _capture_rect(strip_area))
            next_joined_area = _join_area_into_area(target_window, screen, strip_area, joined_area)
            if next_joined_area is not None:
                joined_area = next_joined_area

        _schedule_restore_absolute_area(
            window_manager,
            target_window_ptr,
            final_rect,
            area_type,
            ui_type,
            placement,
            len(strip_areas),
            source_window_ptr_to_close,
            source_area_ptr_for_close["value"],
            action_name,
        )

        if placement in {"LEFT", "RIGHT"}:
            _log_width_debug(
                "place_absolute_joined",
                placement=placement,
                strips=len(strip_areas),
            )
        else:
            _log_height_debug(
                "place_absolute_joined",
                placement=placement,
                strips=len(strip_areas),
            )

        tag_redraw_all(window_manager)
        return None

    bpy.app.timers.register(_finalize, first_interval=0.0)


def _close_source_area(window_manager, source_window_ptr, source_area_ptr):
    source_window = _find_window_by_ptr(window_manager, source_window_ptr)
    if source_window is None or source_window.screen is None:
        return False

    screen = source_window.screen
    if len(screen.areas) <= 1:
        return False

    source_area = _find_area_by_ptr(screen, source_area_ptr)
    if source_area is None:
        return False

    source_region = _preferred_region_for_area(source_area)
    override_kwargs = {
        "window": source_window,
        "screen": screen,
        "area": source_area,
    }
    if source_region is not None:
        override_kwargs["region"] = source_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_close()
    except RuntimeError:
        return False

    return "FINISHED" in result


def _prepare_source_area_for_close(window_manager, source_window_ptr, source_area_ptr):
    source_window = _find_window_by_ptr(window_manager, source_window_ptr)
    if source_window is None or source_window.screen is None:
        return None

    source_area = _find_area_by_ptr(source_window.screen, source_area_ptr)
    if source_area is None:
        return None

    original_state = {
        "area_ptr": source_area_ptr,
        "type": source_area.type,
        "ui_type": getattr(source_area, "ui_type", ""),
    }
    if source_area.type == "VIEW_3D":
        _restore_area_type(source_area, "INFO", "")
        tag_redraw_all(window_manager)
    return original_state


def _restore_prepared_source_area(window_manager, source_window_ptr, prepared_state):
    if not prepared_state:
        return

    source_window = _find_window_by_ptr(window_manager, source_window_ptr)
    if source_window is None or source_window.screen is None:
        return

    source_area = _find_area_by_ptr(source_window.screen, prepared_state.get("area_ptr"))
    if source_area is None:
        return

    area_type = prepared_state.get("type", "")
    if area_type and supports_area(area_type):
        _restore_area_type(source_area, area_type, prepared_state.get("ui_type", ""))


def _schedule_close_source_area(window_manager, source_window_ptr, source_area_ptr, on_done=None):
    prepared_state = _prepare_source_area_for_close(
        window_manager,
        source_window_ptr,
        source_area_ptr,
    )

    def _close():
        if not _close_source_area(window_manager, source_window_ptr, source_area_ptr):
            _restore_prepared_source_area(window_manager, source_window_ptr, prepared_state)
        if on_done is not None:
            on_done()
        return None

    bpy.app.timers.register(_close, first_interval=0.15)


def _schedule_finalize_manual_place(
    window_manager,
    target_window_ptr,
    target_rect,
    before_area_ptrs,
    source_side,
    source_area_state,
    area_type,
    ui_type,
    placement,
    source_window_ptr_to_close=None,
    source_area_ptr_to_close=None,
    action_name="place",
):
    attempts = {"count": 0}

    def _finalize():
        target_window = _find_window_by_ptr(window_manager, target_window_ptr)
        if target_window is None or target_window.screen is None:
            _end_layout_operation()
            return None

        screen = target_window.screen
        candidate_areas = _areas_with_centers_in_rect(screen, target_rect)
        new_areas = [area for area in screen.areas if area.as_pointer() not in before_area_ptrs]
        size_key = _placement_size_key(placement)
        ready_new_areas = [
            area
            for area in new_areas
            if int(round(float(getattr(area, size_key)))) > 0
        ]
        target_size = int(round(float(target_rect[size_key])))

        if placement in {"LEFT", "RIGHT"}:
            _log_width_debug(
                "place_post_split_candidates_deferred",
                placement=placement,
                candidate_widths=[int(round(float(area.width))) for area in candidate_areas],
                new_area_widths=[int(round(float(area.width))) for area in new_areas],
            )
        elif placement in {"TOP", "BOTTOM"}:
            _log_height_debug(
                "place_post_split_candidates_deferred",
                placement=placement,
                candidate_heights=[int(round(float(area.height))) for area in candidate_areas],
                candidate_y=[int(round(float(area.y))) for area in candidate_areas],
                new_area_heights=[int(round(float(area.height))) for area in new_areas],
                new_area_y=[int(round(float(area.y))) for area in new_areas],
            )

        # We need both post-split areas visible before choosing one;
        # otherwise Blender is still exposing stale pre-split geometry.
        stale_split = len(candidate_areas) < 2
        stale_single_candidate = (
            len(candidate_areas) == 1 and
            len(new_areas) == 0 and
            int(round(float(getattr(candidate_areas[0], size_key)))) == target_size
        )
        if stale_split or stale_single_candidate:
            attempts["count"] += 1
            if attempts["count"] >= 20:
                _log_action_debug(
                    "attach_failed",
                    action=action_name,
                    placement=placement,
                    reason="split_stale",
                    target_rect=f"({_format_rect_from_values(target_rect['x'], target_rect['y'], target_rect['width'], target_rect['height'])})",
                )
                _end_layout_operation()
                return None
            return 0.05

        if placement in {"TOP", "BOTTOM"}:
            # Blender may keep the detached-sized area as either the original
            # area or the new one, depending on which side is larger. Keep the
            # requested physical side primary, then match detached height there.
            side_candidate_areas = [
                area for area in candidate_areas
                if _area_center_is_on_rect_side(area, target_rect, placement)
            ]
            recreated_area = _pick_area_matching_detached_size(
                side_candidate_areas,
                source_area_state,
                placement,
                source_side,
            )
            if recreated_area is None:
                recreated_area = _pick_area_matching_detached_size(
                    candidate_areas,
                    source_area_state,
                    placement,
                    source_side,
                )
            if recreated_area is None:
                recreated_area = _pick_area_matching_detached_size(
                    ready_new_areas,
                    source_area_state,
                    placement,
                    source_side,
                )
        else:
            recreated_area = _pick_area_on_source_side(candidate_areas, source_side)
            if recreated_area is None:
                recreated_area = _pick_area_on_source_side(new_areas, source_side)
        if recreated_area is None:
            attempts["count"] += 1
            if attempts["count"] >= 20:
                _log_action_debug(
                    "attach_failed",
                    action=action_name,
                    placement=placement,
                    reason="recreated_area_missing",
                    target_rect=f"({_format_rect_from_values(target_rect['x'], target_rect['y'], target_rect['width'], target_rect['height'])})",
                )
                _end_layout_operation()
                return None
            return 0.05

        if placement in {"LEFT", "RIGHT"}:
            _log_width_debug(
                "place_selected_area_deferred",
                placement=placement,
                selected_width=int(round(float(recreated_area.width))),
                source_side=source_side,
            )
        elif placement in {"TOP", "BOTTOM"}:
            _log_height_debug(
                "place_selected_area_deferred",
                placement=placement,
                selected_height=int(round(float(recreated_area.height))),
                selected_y=int(round(float(recreated_area.y))),
                source_side=source_side,
            )

        _restore_area_type(recreated_area, area_type, ui_type)
        _log_action_debug(
            "attached",
            action=action_name,
            placement=placement,
            editor=area_type_label(area_type),
            attached_as=_describe_area(target_window, recreated_area),
            target_rect=f"({_format_rect_from_values(target_rect['x'], target_rect['y'], target_rect['width'], target_rect['height'])})",
            source_side=source_side,
            closed_source_window=source_window_ptr_to_close or "",
            closed_source_area=source_area_ptr_to_close or "",
        )
        if (
            source_window_ptr_to_close is not None and
            source_area_ptr_to_close is not None and
            recreated_area.as_pointer() != source_area_ptr_to_close
        ):
            def _finish_after_close():
                tag_redraw_all(window_manager)
                _end_layout_operation()

            _schedule_close_source_area(
                window_manager,
                source_window_ptr_to_close,
                source_area_ptr_to_close,
                _finish_after_close,
            )
            return None

        tag_redraw_all(window_manager)
        _end_layout_operation()
        return None

    bpy.app.timers.register(_finalize, first_interval=0.0)


def recreate_editor_in_source_window(window_manager, detached_window):
    if detached_window is None:
        return False

    detached_info = _detached_windows.get(detached_window.as_pointer())
    if detached_info is None:
        return False

    source_window = _find_window_by_ptr(window_manager, detached_info["source_window_ptr"])
    if source_window is None or source_window.screen is None:
        for candidate in window_manager.windows:
            if candidate.as_pointer() != detached_window.as_pointer() and not is_detached_window(candidate):
                source_window = candidate
                break
    if source_window is None or source_window.screen is None:
        return False

    screen = source_window.screen
    source_area_state = detached_info.get("source_area_state") or {}
    target_area = _find_return_target_area(screen, source_area_state)
    if target_area is None:
        return False

    before_area_ptrs = {area.as_pointer() for area in screen.areas}
    split_geometry = _compute_split_geometry(target_area, source_area_state)
    combined_rect = source_area_state.get("combined_rect") or _capture_rect(target_area)
    target_region = _preferred_region_for_area(target_area)
    override_kwargs = {
        "window": source_window,
        "screen": screen,
        "area": target_area,
    }
    if target_region is not None:
        override_kwargs["region"] = target_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_split(
                direction=split_geometry["direction"],
                factor=split_geometry["factor"],
                cursor=split_geometry["cursor"],
            )
    except RuntimeError:
        return False

    if "FINISHED" not in result:
        return False

    recreated_area = _pick_area_on_source_side(
        _areas_with_centers_in_rect(screen, combined_rect),
        split_geometry.get("source_side"),
    )
    if recreated_area is None:
        new_areas = [area for area in screen.areas if area.as_pointer() not in before_area_ptrs]
        recreated_area = new_areas[0] if new_areas else None
    if recreated_area is None:
        return False

    _restore_area_type(
        recreated_area,
        detached_info["area_type"],
        source_area_state.get("ui_type", ""),
    )
    return True


def place_detached_window(window_manager, detached_window, target_window_ptr, target_area_ptr, placement):
    if not _begin_layout_operation():
        return False

    if detached_window is None:
        _end_layout_operation()
        return False

    detached_info = _detached_windows.get(detached_window.as_pointer())
    if detached_info is None:
        _end_layout_operation()
        return False

    target_window = _find_window_by_ptr(window_manager, target_window_ptr)
    if (
        target_window is None or
        target_window.screen is None or
        is_detached_window(target_window)
    ):
        _log_action_debug(
            "request_failed",
            action="place",
            placement=placement,
            called_by=_describe_detached_window(detached_window, detached_info),
            target_window=target_window_ptr,
            reason="target_window_unavailable",
        )
        _end_layout_operation()
        return False

    target_area = _find_area_by_ptr(target_window.screen, target_area_ptr)
    if target_area is None or not supports_area(target_area.type):
        _log_action_debug(
            "request_failed",
            action="place",
            placement=placement,
            called_by=_describe_detached_window(detached_window, detached_info),
            target_window=_describe_window(target_window),
            target_area=target_area_ptr,
            reason="target_area_unavailable",
        )
        _end_layout_operation()
        return False

    screen = target_window.screen
    source_area_state = _capture_detached_window_area_state(
        detached_window,
        detached_info.get("source_area_state") or {},
    )
    _log_action_debug(
        "requested",
        action="place",
        placement=placement,
        called_by=_describe_detached_window(detached_window, detached_info, source_area_state),
        target=_describe_area(target_window, target_area),
    )
    split_area = target_area
    split_source_side = placement
    if placement in {"LEFT", "RIGHT"}:
        _log_width_debug(
            "place_prepare",
            placement=placement,
            target_width=int(round(float(target_area.width))),
            detached_width=int(round(float(source_area_state.get("width", 0.0)))),
            split_area_width=int(round(float(split_area.width))),
            split_source_side=split_source_side,
        )
    elif placement in {"TOP", "BOTTOM"}:
        _log_height_debug(
            "place_prepare",
            placement=placement,
            target_height=int(round(float(target_area.height))),
            detached_height=int(round(float(source_area_state.get("height", 0.0)))),
            split_area_height=int(round(float(split_area.height))),
            split_source_side=split_source_side,
        )

    target_rect = _capture_rect(split_area)
    before_area_ptrs = {area.as_pointer() for area in screen.areas}
    split_geometry = _compute_manual_split_geometry(split_area, source_area_state, split_source_side)
    target_region = _preferred_region_for_area(split_area)
    override_kwargs = {
        "window": target_window,
        "screen": screen,
        "area": split_area,
    }
    if target_region is not None:
        override_kwargs["region"] = target_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_split(
                direction=split_geometry["direction"],
                factor=split_geometry["factor"],
                cursor=split_geometry["cursor"],
            )
    except RuntimeError:
        _end_layout_operation()
        return False

    if "FINISHED" not in result:
        _end_layout_operation()
        return False

    _schedule_finalize_manual_place(
        window_manager,
        target_window_ptr,
        target_rect,
        before_area_ptrs,
        split_geometry["source_side"],
        source_area_state,
        detached_info["area_type"],
        source_area_state.get("ui_type", ""),
        placement,
        action_name="place",
    )
    return True


def place_detached_window_absolute(window_manager, detached_window, placement):
    if not _begin_layout_operation():
        return False

    sync_detached_windows(window_manager)

    if detached_window is None:
        _end_layout_operation()
        return False

    detached_info = _detached_windows.get(detached_window.as_pointer())
    if detached_info is None:
        _end_layout_operation()
        return False

    target = _find_absolute_place_target(window_manager, detached_window, placement)
    if target is None:
        _log_action_debug(
            "request_failed",
            action="place_absolute",
            placement=placement,
            called_by=_describe_detached_window(detached_window, detached_info),
            reason="edge_target_missing",
        )
        _end_layout_operation()
        return False

    target_window = target["window"]
    if (
        target_window is None or
        target_window.screen is None or
        is_detached_window(target_window)
    ):
        _end_layout_operation()
        return False

    screen = target_window.screen
    area = target["area"]
    screen_bounds = target.get("screen_bounds") or _screen_area_bounds(target["window"].screen) or {}
    edge_coverage = round(_edge_coverage(area, screen_bounds, placement), 4) if screen_bounds else 0.0
    if placement in {"LEFT", "RIGHT"}:
        _log_width_debug(
            "place_absolute_target",
            placement=placement,
            target=target["label"],
            target_x=int(round(float(area.x))),
            target_width=int(round(float(area.width))),
            target_height=int(round(float(area.height))),
            screen_height=int(round(float(screen_bounds.get("height", 0.0)))),
            edge_coverage=edge_coverage,
        )
    else:
        _log_height_debug(
            "place_absolute_target",
            placement=placement,
            target=target["label"],
            target_y=int(round(float(area.y))),
            target_width=int(round(float(area.width))),
            target_height=int(round(float(area.height))),
            screen_width=int(round(float(screen_bounds.get("width", 0.0)))),
            edge_coverage=edge_coverage,
        )

    source_area_state = _capture_detached_window_area_state(
        detached_window,
        detached_info.get("source_area_state") or {},
    )
    source_area_state = _area_state_for_absolute_placement(
        source_area_state,
        screen_bounds,
        placement,
    )
    edge_areas = _areas_touching_screen_edge(screen, screen_bounds, placement)
    source_area_state = _area_state_for_absolute_edge_areas(
        source_area_state,
        edge_areas,
        placement,
    )
    _log_action_debug(
        "requested",
        action="place_absolute",
        placement=placement,
        called_by=_describe_detached_window(detached_window, detached_info, source_area_state),
        target_edge=_describe_area(target_window, area),
        edge_areas=len(edge_areas),
        screen_bounds=f"({_format_rect_from_values(screen_bounds.get('x', 0), screen_bounds.get('y', 0), screen_bounds.get('width', 0), screen_bounds.get('height', 0))})",
    )
    split_records = []

    for edge_area in list(edge_areas):
        if _find_area_by_ptr(screen, edge_area.as_pointer()) is None:
            continue

        target_rect = _capture_rect(edge_area)
        before_area_ptrs = {area.as_pointer() for area in screen.areas}
        split_geometry = _compute_manual_split_geometry(edge_area, source_area_state, placement)
        target_region = _preferred_region_for_area(edge_area)
        override_kwargs = {
            "window": target_window,
            "screen": screen,
            "area": edge_area,
        }
        if target_region is not None:
            override_kwargs["region"] = target_region

        try:
            with bpy.context.temp_override(**override_kwargs):
                result = bpy.ops.screen.area_split(
                    direction=split_geometry["direction"],
                    factor=split_geometry["factor"],
                    cursor=split_geometry["cursor"],
                )
        except RuntimeError:
            continue

        if "FINISHED" not in result:
            continue

        split_records.append(
            {
                "target_rect": target_rect,
                "before_area_ptrs": before_area_ptrs,
                "source_side": split_geometry["source_side"],
                "split_area_ptr": edge_area.as_pointer(),
                "target_area_type": edge_area.type,
                "target_ui_type": getattr(edge_area, "ui_type", ""),
            }
        )

    if not split_records:
        _log_action_debug(
            "request_failed",
            action="place_absolute",
            placement=placement,
            called_by=_describe_detached_window(detached_window, detached_info, source_area_state),
            target_edge=_describe_area(target_window, area),
            reason="split_failed",
        )
        _end_layout_operation()
        return False

    if placement in {"LEFT", "RIGHT"}:
        _log_width_debug(
            "place_absolute_splits",
            placement=placement,
            split_count=len(split_records),
            edge_count=len(edge_areas),
        )
    else:
        _log_height_debug(
            "place_absolute_splits",
            placement=placement,
            split_count=len(split_records),
            edge_count=len(edge_areas),
        )

    _schedule_finalize_absolute_place(
        window_manager,
        target_window.as_pointer(),
        split_records,
        source_area_state,
        detached_info["area_type"],
        source_area_state.get("ui_type", ""),
        placement,
        action_name="place_absolute",
    )
    return True


def move_area_to_target(window_manager, source_window, source_area, target_window_ptr, target_area_ptr, placement):
    if not _begin_layout_operation():
        return False

    if (
        source_window is None or
        source_window.screen is None or
        source_area is None or
        not supports_area(source_area.type) or
        len(source_window.screen.areas) <= 1
    ):
        _end_layout_operation()
        return False

    target_window = _find_window_by_ptr(window_manager, target_window_ptr)
    if (
        target_window is None or
        target_window.screen is None or
        is_detached_window(target_window)
    ):
        _log_action_debug(
            "request_failed",
            action="move",
            placement=placement,
            called_by=_describe_area(source_window, source_area),
            target_window=target_window_ptr,
            reason="target_window_unavailable",
        )
        _end_layout_operation()
        return False

    target_area = _find_area_by_ptr(target_window.screen, target_area_ptr)
    if target_area is None or not supports_area(target_area.type):
        _log_action_debug(
            "request_failed",
            action="move",
            placement=placement,
            called_by=_describe_area(source_window, source_area),
            target_window=_describe_window(target_window),
            target_area=target_area_ptr,
            reason="target_area_unavailable",
        )
        _end_layout_operation()
        return False
    if (
        target_window.as_pointer() == source_window.as_pointer() and
        target_area.as_pointer() == source_area.as_pointer()
    ):
        _end_layout_operation()
        return False

    screen = target_window.screen
    source_area_state = _capture_area_state(source_area)
    _log_action_debug(
        "requested",
        action="move",
        placement=placement,
        called_by=_describe_area(source_window, source_area),
        target=_describe_area(target_window, target_area),
    )
    split_geometry = _compute_manual_split_geometry(target_area, source_area_state, placement)
    target_rect = _capture_rect(target_area)
    before_area_ptrs = {area.as_pointer() for area in screen.areas}
    target_region = _preferred_region_for_area(target_area)
    override_kwargs = {
        "window": target_window,
        "screen": screen,
        "area": target_area,
    }
    if target_region is not None:
        override_kwargs["region"] = target_region

    try:
        with bpy.context.temp_override(**override_kwargs):
            result = bpy.ops.screen.area_split(
                direction=split_geometry["direction"],
                factor=split_geometry["factor"],
                cursor=split_geometry["cursor"],
            )
    except RuntimeError:
        _end_layout_operation()
        return False

    if "FINISHED" not in result:
        _end_layout_operation()
        return False

    _schedule_finalize_manual_place(
        window_manager,
        target_window_ptr,
        target_rect,
        before_area_ptrs,
        split_geometry["source_side"],
        source_area_state,
        source_area.type,
        source_area_state.get("ui_type", ""),
        placement,
        source_window.as_pointer(),
        source_area.as_pointer(),
        "move",
    )
    return True


def _execute_move_area_absolute(window_manager, source_window_ptr, source_area_ptr, placement):
    sync_detached_windows(window_manager)

    source_window = _find_window_by_ptr(window_manager, source_window_ptr)
    source_area = _find_area_by_ptr(
        source_window.screen if source_window is not None else None,
        source_area_ptr,
    )
    if (
        source_window is None or
        source_window.screen is None or
        source_area is None or
        not supports_area(source_area.type) or
        len(source_window.screen.areas) <= 1
    ):
        _end_layout_operation()
        return None

    target = _find_absolute_place_target(window_manager, None, placement)
    if target is None:
        _log_action_debug(
            "request_failed",
            action="move_absolute",
            placement=placement,
            called_by=_describe_area(source_window, source_area),
            reason="edge_target_missing",
        )
        _end_layout_operation()
        return None

    target_window = target["window"]
    if (
        target_window is None or
        target_window.screen is None or
        is_detached_window(target_window)
    ):
        _end_layout_operation()
        return None

    screen = target_window.screen
    screen_bounds = target.get("screen_bounds") or _screen_area_bounds(screen) or {}
    source_area_state = _area_state_for_absolute_placement(
        _capture_area_state(source_area),
        screen_bounds,
        placement,
    )
    edge_areas = _areas_touching_screen_edge(screen, screen_bounds, placement)
    source_area_state = _area_state_for_absolute_edge_areas(
        source_area_state,
        edge_areas,
        placement,
    )
    _log_action_debug(
        "requested",
        action="move_absolute",
        placement=placement,
        called_by=_describe_area(source_window, source_area),
        target_edge=_describe_area(target_window, target["area"]),
        edge_areas=len(edge_areas),
        screen_bounds=f"({_format_rect_from_values(screen_bounds.get('x', 0), screen_bounds.get('y', 0), screen_bounds.get('width', 0), screen_bounds.get('height', 0))})",
    )
    split_records = []

    for edge_area in list(edge_areas):
        if _find_area_by_ptr(screen, edge_area.as_pointer()) is None:
            continue

        target_rect = _capture_rect(edge_area)
        before_area_ptrs = {area.as_pointer() for area in screen.areas}
        split_geometry = _compute_manual_split_geometry(edge_area, source_area_state, placement)
        target_region = _preferred_region_for_area(edge_area)
        override_kwargs = {
            "window": target_window,
            "screen": screen,
            "area": edge_area,
        }
        if target_region is not None:
            override_kwargs["region"] = target_region

        try:
            with bpy.context.temp_override(**override_kwargs):
                result = bpy.ops.screen.area_split(
                    direction=split_geometry["direction"],
                    factor=split_geometry["factor"],
                    cursor=split_geometry["cursor"],
                )
        except RuntimeError:
            continue

        if "FINISHED" not in result:
            continue

        split_records.append(
            {
                "target_rect": target_rect,
                "before_area_ptrs": before_area_ptrs,
                "source_side": split_geometry["source_side"],
                "split_area_ptr": edge_area.as_pointer(),
                "target_area_type": edge_area.type,
                "target_ui_type": getattr(edge_area, "ui_type", ""),
            }
        )

    if not split_records:
        _log_action_debug(
            "request_failed",
            action="move_absolute",
            placement=placement,
            called_by=_describe_area(source_window, source_area),
            target_edge=_describe_area(target_window, target["area"]),
            reason="split_failed",
        )
        _end_layout_operation()
        return None

    _schedule_finalize_absolute_place(
        window_manager,
        target_window.as_pointer(),
        split_records,
        source_area_state,
        source_area.type,
        source_area_state.get("ui_type", ""),
        placement,
        source_window.as_pointer(),
        source_area.as_pointer(),
        "move_absolute",
    )
    return None


def move_area_absolute(window_manager, source_window, source_area, placement):
    if not _begin_layout_operation():
        return False

    if (
        source_window is None or
        source_window.screen is None or
        source_area is None or
        not supports_area(source_area.type) or
        len(source_window.screen.areas) <= 1
    ):
        _end_layout_operation()
        return False

    source_window_ptr = source_window.as_pointer()
    source_area_ptr = source_area.as_pointer()

    def _move_after_ui_idle():
        _execute_move_area_absolute(
            window_manager,
            source_window_ptr,
            source_area_ptr,
            placement,
        )
        return None

    bpy.app.timers.register(_move_after_ui_idle, first_interval=0.15)
    return True


def schedule_finalize_detach(
    window_manager,
    before_window_ptrs,
    source_window_ptr,
    source_area_ptr,
    area_type,
):
    attempts = {"count": 0}

    def _finalize():
        cleanup_closed_windows(window_manager)

        current_windows = {
            window.as_pointer(): window
            for window in window_manager.windows
            if window.as_pointer() not in _closing_window_ptrs
        }
        new_window_ptrs = [ptr for ptr in current_windows if ptr not in before_window_ptrs]

        if new_window_ptrs:
            source_window = _find_window_by_ptr(window_manager, source_window_ptr)
            source_area = _find_area_by_ptr(source_window.screen if source_window else None, source_area_ptr)
            if source_area is None:
                return None
            source_area_state = _capture_area_state(source_area)
            neighbor_info = _find_absorbing_neighbor(
                source_window.screen if source_window else None,
                source_area,
            )
            if neighbor_info:
                source_area_state.update(neighbor_info)
                if source_area_state.get("source_side") in {"LEFT", "RIGHT"}:
                    target_area_state = source_area_state.get("target_area_state") or {}
                    combined_rect = source_area_state.get("combined_rect") or {}
                    _log_width_debug(
                        "detach_capture",
                        source_side=source_area_state.get("source_side"),
                        detached_width=int(round(float(source_area_state.get("width", 0.0)))),
                        neighbor_width=int(round(float(target_area_state.get("width", 0.0)))),
                        combined_width=int(round(float(combined_rect.get("width", 0.0)))),
                    )
                elif source_area_state.get("source_side") in {"TOP", "BOTTOM"}:
                    target_area_state = source_area_state.get("target_area_state") or {}
                    combined_rect = source_area_state.get("combined_rect") or {}
                    _log_height_debug(
                        "detach_capture",
                        source_side=source_area_state.get("source_side"),
                        detached_height=int(round(float(source_area_state.get("height", 0.0)))),
                        neighbor_height=int(round(float(target_area_state.get("height", 0.0)))),
                        combined_height=int(round(float(combined_rect.get("height", 0.0)))),
                    )
            mark_detached_window(
                new_window_ptrs[0],
                source_window_ptr,
                area_type,
                source_area_state,
            )
            new_window = current_windows.get(new_window_ptrs[0])
            _log_action_debug(
                "detached",
                action="detach",
                called_by=_describe_area(source_window, source_area),
                detached_window=_describe_window(new_window),
                editor=area_type_label(area_type),
                captured_source=_describe_area_state(area_type, source_area_state),
            )
            _close_source_area(window_manager, source_window_ptr, source_area_ptr)
            tag_redraw_all(window_manager)
            return None

        attempts["count"] += 1
        if attempts["count"] >= 20:
            _log_action_debug(
                "detach_failed",
                action="detach",
                source_window=source_window_ptr,
                source_area=source_area_ptr,
                editor=area_type_label(area_type),
                reason="new_window_missing",
            )
            return None
        return 0.1

    bpy.app.timers.register(_finalize, first_interval=0.05)


def tag_redraw_all(window_manager):
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            for region in area.regions:
                region.tag_redraw()


def sync_detached_windows(window_manager=None):
    window_manager = window_manager or getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    cleanup_closed_windows(window_manager)


def _sync_detached_windows_once():
    global _detached_sync_timer_pending
    _detached_sync_timer_pending = False

    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return None

    sync_detached_windows(window_manager)
    tag_redraw_all(window_manager)
    return None


def schedule_detached_window_sync(first_interval=0.1):
    global _detached_sync_timer_pending
    if _detached_sync_timer_pending:
        return
    _detached_sync_timer_pending = True
    bpy.app.timers.register(_sync_detached_windows_once, first_interval=first_interval)


@persistent
def _load_post_sync_detached_windows(_dummy):
    schedule_detached_window_sync(0.1)


def register():
    if _load_post_sync_detached_windows not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_sync_detached_windows)
    schedule_detached_window_sync(0.1)


def unregister():
    global _detached_sync_timer_pending
    _detached_sync_timer_pending = False
    if _load_post_sync_detached_windows in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_sync_detached_windows)
