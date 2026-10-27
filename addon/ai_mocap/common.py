"""Small helpers shared by operators and UI (main thread only)."""

import os
import time

import bpy

from . import engine_env as E

PACKAGE = __package__


def prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(PACKAGE)
    return addon.preferences if addon else None


def paths(context=None):
    p = prefs(context)
    override = getattr(p, "data_dir", "") if p else ""
    data_dir = bpy.path.abspath(override) if override else E.default_data_dir(PACKAGE)
    return E.Paths(data_dir)


def base_python(context=None):
    p = prefs(context)
    return E.base_python(bpy.path.abspath(p.base_python) if p and p.base_python else "")


def online():
    """Extensions must respect Blender's «Allow Online Access» setting."""
    return bool(getattr(bpy.app, "online_access", True))


def redraw_all():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'PREFERENCES', 'PROPERTIES', 'DOPESHEET_EDITOR',
                             'GRAPH_EDITOR', 'NLA_EDITOR'}:
                area.tag_redraw()


_size_cache = {}


def cached_folder_size(path, ttl=10.0):
    now = time.monotonic()
    hit = _size_cache.get(path)
    if hit and now - hit[0] < ttl:
        return hit[1]
    size = E.folder_size(path) if os.path.isdir(path) else 0
    _size_cache[path] = (now, size)
    return size


def invalidate_sizes():
    _size_cache.clear()


def scene_fps(scene):
    return scene.render.fps / (scene.render.fps_base or 1.0)
