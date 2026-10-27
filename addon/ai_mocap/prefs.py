"""Add-on preferences: install, verify and remove the capture engine and models."""

import os

import bpy
from bpy.props import StringProperty
from bpy.types import AddonPreferences

from . import common
from . import engine_env as E
from .core import tasks

STATE_ICONS = {"READY": 'CHECKMARK', "NOT_INSTALLED": 'ERROR', "OUTDATED": 'ERROR',
               "UNVERIFIED": 'QUESTION'}
STATE_TEXT = {"READY": "Listo", "NOT_INSTALLED": "No instalado", "OUTDATED": "Necesita actualizarse",
              "UNVERIFIED": "Sin verificar"}


def draw_task_box(layout, kinds=None):
    """Progress of the running task, or the outcome of the last one."""
    task = tasks.current()
    if task is not None and (kinds is None or task.kind in kinds):
        box = layout.box()
        row = box.row()
        row.label(text=task.title, icon='TIME')
        row.operator("ai_mocap.cancel_task", text="Cancelar", icon='CANCEL')
        text = task.stage + (f" · {task.message}" if task.message else "")
        if task.total:
            box.progress(factor=task.factor, type='BAR', text=text or "…")
        else:
            box.label(text=text or "…")
        box.label(text=f"Tiempo: {task.elapsed:.0f} s", icon='BLANK1')
        return True
    last = tasks.last()
    if last is not None and (kinds is None or last.kind in kinds):
        box = layout.box()
        if last.state == tasks.DONE:
            box.label(text=f"{last.title}: completado en {last.elapsed:.1f} s", icon='CHECKMARK')
            if last.finish_note:
                for line in last.finish_note.splitlines():
                    box.label(text=line, icon='BLANK1')
        elif last.state == tasks.CANCELLED:
            box.label(text=f"{last.title}: cancelado", icon='CANCEL')
        else:
            box.alert = True
            box.label(text=f"{last.title}: error", icon='ERROR')
            col = box.column(align=True)
            for line in (last.error or "").splitlines()[:8]:
                col.label(text=line[:120])
            row = box.row()
            op = row.operator("ai_mocap.open_path", text="Ver registro", icon='TEXT')
            op.path = last.log_path
        row = box.row()
        row.alignment = 'RIGHT'
        row.operator("ai_mocap.dismiss_task", text="", icon='X', emboss=False)
    return False


class AIMOCAP_AP_preferences(AddonPreferences):
    bl_idname = common.PACKAGE

    data_dir: StringProperty(
        name="Carpeta de datos", subtype='DIR_PATH', default="",
        description="Dónde guardar el motor (~470 MB), los modelos y la caché. Vacío = carpeta de "
                    "usuario de la extensión. Útil si la ruta es muy larga o el disco está lleno")
    base_python: StringProperty(
        name="Python base", subtype='FILE_PATH', default="",
        description="Intérprete con el que se crea el entorno del motor. Vacío = el Python de Blender")

    def draw(self, context):
        layout = self.layout
        paths = common.paths(context)
        state, detail = E.engine_state(paths)

        box = layout.box()
        row = box.row()
        row.label(text="Motor de captura (MediaPipe, en local)", icon='ARMATURE_DATA')
        row.label(text=STATE_TEXT[state], icon=STATE_ICONS[state])
        box.label(text=detail, icon='BLANK1')
        if not common.online() and state != "READY":
            warn = box.box()
            warn.alert = True
            warn.label(text="Blender no tiene permitido el acceso a internet.", icon='URL')
            warn.label(text="Actívalo en Sistema → Red → «Permitir acceso en línea» para instalar.",
                       icon='BLANK1')
        busy = tasks.busy()
        row = box.row(align=True)
        row.enabled = not busy
        if state == "NOT_INSTALLED":
            row.operator("ai_mocap.install_engine", text="Instalar motor", icon='IMPORT').reinstall = False
        else:
            if state == "OUTDATED":
                row.operator("ai_mocap.install_engine", text="Actualizar motor",
                             icon='FILE_REFRESH').reinstall = False
            row.operator("ai_mocap.verify_engine", text="Verificar", icon='CHECKMARK')
            row.operator("ai_mocap.install_engine", text="Reinstalar", icon='FILE_REFRESH').reinstall = True
            row.operator("ai_mocap.remove_engine", text="Eliminar", icon='TRASH')
        draw_task_box(box, kinds={"install", "model", "verify"})

        col = box.column(align=True)
        col.label(text="Modelos de pose:")
        for key, info in E.MODELS.items():
            r = col.row(align=True)
            ok = paths.model_ok(key)
            r.label(text=f"{info['label']} · {info['size'] / 1048576:.1f} MB",
                    icon='CHECKMARK' if ok else 'DOT')
            sub = r.row(align=True)
            sub.enabled = not busy and os.path.isfile(paths.python)
            sub.operator("ai_mocap.download_model", text="Descargado" if ok else "Descargar",
                         icon='IMPORT').variant = key

        box = layout.box()
        box.label(text="Caché de análisis", icon='FILE_CACHE')
        row = box.row()
        row.label(text="Ocupa " + E.human_size(common.cached_folder_size(paths.cache)))
        row.operator("ai_mocap.clear_cache", text="Vaciar caché", icon='TRASH')

        box = layout.box()
        box.label(text="Ubicación", icon='FILE_FOLDER')
        row = box.row()
        row.label(text=paths.data_dir)
        row.operator("ai_mocap.open_path", text="", icon='FILE_FOLDER').path = paths.data_dir
        box.prop(self, "data_dir")
        box.prop(self, "base_python")
        box.label(text="Python base actual: " + common.base_python(context), icon='BLANK1')


def register():
    bpy.utils.register_class(AIMOCAP_AP_preferences)


def unregister():
    bpy.utils.unregister_class(AIMOCAP_AP_preferences)
