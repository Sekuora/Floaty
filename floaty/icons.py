ATTACHED_WINDOW_ICON = "AREA_DOCK"
DETACHED_WINDOW_ICON = "AREA_SWAP"


def register():
    pass


def unregister():
    pass


def get_detach_icon():
    return {"icon": ATTACHED_WINDOW_ICON}


def get_place_icon():
    return {"icon": DETACHED_WINDOW_ICON}


def get_push_icon():
    return get_place_icon()
