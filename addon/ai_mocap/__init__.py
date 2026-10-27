"""AI Mocap: editable animation from a reference video, with local AI.

Panels live in View3D → Sidebar (N) → «AI Mocap». The capture engine
(MediaPipe) runs in its own environment, installed from the add-on
preferences; Blender's Python is never modified.

Blender modules are imported inside register() so the pure-Python parts
(retargeting maths, mapping, cache) stay importable by the unit tests.
"""

_handler = None


def _modules():
    from . import operators, prefs, properties, ui
    return (properties, prefs, operators, ui)


def register():
    global _handler
    import bpy
    from bpy.app.handlers import persistent
    from . import common
    from .core import tasks

    @persistent
    def on_load_pre(*_args):
        # A running capture refers to objects of the file being closed.
        tasks.shutdown()

    for mod in _modules():
        mod.register()
    tasks.set_redraw_callback(common.redraw_all)
    _handler = on_load_pre
    bpy.app.handlers.load_pre.append(_handler)


def unregister():
    global _handler
    import bpy
    from .core import tasks
    tasks.shutdown()
    tasks.set_redraw_callback(None)
    if _handler in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_handler)
    _handler = None
    for mod in reversed(_modules()):
        mod.unregister()
