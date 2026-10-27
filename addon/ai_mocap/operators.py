"""Operators (buttons) of the add-on."""

import json
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import common
from . import engine_env as E
from .core import cache, generation, tasks, workers
from .core.generation import GenerateError
from .rig import presets as P
from .rig.detect import find_armature
from .rig.mapping import auto_map


def _start_task(op, title, kind, worker, on_finish=None, context=None):
    paths = common.paths(context)
    try:
        tasks.start(tasks.Task(title, worker, on_finish, kind=kind, log_dir=paths.logs))
    except tasks.TaskError as exc:
        op.report({'ERROR'}, exc.message)
        return {'CANCELLED'}
    common.redraw_all()
    return {'FINISHED'}


# --- Engine (preferences) ---------------------------------------------------

class AIMOCAP_OT_install_engine(Operator):
    bl_idname = "ai_mocap.install_engine"
    bl_label = "Instalar motor de captura"
    bl_description = ("Crea un entorno aislado con el Python de Blender e instala MediaPipe, OpenCV y "
                      "NumPy (~470 MB) y el modelo de pose. No modifica el Python de Blender")
    reinstall: BoolProperty(default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.reinstall:
            return context.window_manager.invoke_confirm(
                self, event, title="Reinstalar el motor",
                message="Se borrará el entorno actual y se volverá a descargar (~470 MB).",
                confirm_text="Reinstalar")
        return self.execute(context)

    def execute(self, context):
        if not common.online():
            self.report({'ERROR'}, "Activa «Permitir acceso en línea» en Preferencias → Sistema → Red.")
            return {'CANCELLED'}
        paths = common.paths(context)
        base = common.base_python(context)
        variant = context.scene.ai_mocap.model_variant if context.scene else "full"
        reinstall = self.reinstall

        def worker(ctx):
            return workers.install_engine(ctx, paths, base, variant, True, reinstall)

        def done(task):
            E.invalidate_status()
            if task.state == tasks.DONE:
                v = task.result["versions"]
                task.finish_note = f"MediaPipe {v.get('mediapipe')} · OpenCV {v.get('opencv')}"
        return _start_task(self, "Instalando motor", "install", worker, done, context)


class AIMOCAP_OT_verify_engine(Operator):
    bl_idname = "ai_mocap.verify_engine"
    bl_label = "Verificar motor"
    bl_description = "Comprueba que el motor arranca, carga el modelo y procesa una imagen de prueba"

    def execute(self, context):
        paths = common.paths(context)
        variant = next((k for k in ("full", "lite", "heavy") if paths.model_ok(k)), "full")
        base = common.base_python(context)

        def done(task):
            E.invalidate_status()
        return _start_task(self, "Verificando motor", "verify",
                           lambda ctx: workers.verify_engine(ctx, paths, variant, base), done, context)


class AIMOCAP_OT_download_model(Operator):
    bl_idname = "ai_mocap.download_model"
    bl_label = "Descargar modelo"
    bl_description = "Descarga el modelo de pose y comprueba su huella SHA-256"
    variant: StringProperty(default="full")

    def execute(self, context):
        if self.variant not in E.MODELS:
            return {'CANCELLED'}
        paths = common.paths(context)
        online, variant = common.online(), self.variant
        return _start_task(self, "Descargando modelo", "model",
                           lambda ctx: workers.download_model(ctx, paths, variant, online),
                           None, context)


class AIMOCAP_OT_remove_engine(Operator):
    bl_idname = "ai_mocap.remove_engine"
    bl_label = "Eliminar motor"
    bl_description = "Borra el entorno del motor (no borra los modelos ni la caché)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Eliminar el motor de captura",
            message="Habrá que volver a instalarlo para generar animaciones.", confirm_text="Eliminar")

    def execute(self, context):
        import shutil
        if tasks.busy():
            self.report({'ERROR'}, "Hay una tarea en curso.")
            return {'CANCELLED'}
        paths = common.paths(context)
        shutil.rmtree(paths.venv, ignore_errors=True)
        try:
            os.remove(paths.status)
        except OSError:
            pass
        E.invalidate_status()
        self.report({'INFO'}, "Motor eliminado.")
        return {'FINISHED'}


class AIMOCAP_OT_clear_cache(Operator):
    bl_idname = "ai_mocap.clear_cache"
    bl_label = "Vaciar caché"
    bl_description = "Borra los análisis de vídeo guardados (las Actions ya creadas no se tocan)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if tasks.busy():
            self.report({'ERROR'}, "Hay una tarea en curso.")
            return {'CANCELLED'}
        cache.clear(common.paths(context).cache)
        common.invalidate_sizes()
        self.report({'INFO'}, "Caché vaciada.")
        return {'FINISHED'}


class AIMOCAP_OT_cancel_task(Operator):
    bl_idname = "ai_mocap.cancel_task"
    bl_label = "Cancelar"
    bl_description = "Detiene la tarea en curso (el personaje no se modifica)"

    def execute(self, context):
        tasks.cancel()
        return {'FINISHED'}


class AIMOCAP_OT_dismiss_task(Operator):
    bl_idname = "ai_mocap.dismiss_task"
    bl_label = "Cerrar aviso"
    bl_description = "Oculta el resultado de la última tarea"

    def execute(self, context):
        tasks.clear_last()
        common.redraw_all()
        return {'FINISHED'}


class AIMOCAP_OT_open_path(Operator):
    bl_idname = "ai_mocap.open_path"
    bl_label = "Abrir"
    bl_description = "Abre la carpeta o el archivo con el explorador del sistema"
    path: StringProperty()

    def execute(self, context):
        if not self.path or not os.path.exists(self.path):
            self.report({'ERROR'}, "No existe: " + self.path)
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=self.path)
        return {'FINISHED'}


# --- A · Character ------------------------------------------------------------

def _analyze(op, arm, keep_manual=False):
    names = [b.name for b in arm.data.bones]
    mapping, report = auto_map(names)
    rig = arm.data.ai_mocap
    if keep_manual:
        mapping.update({k: v for k, v in rig.mapping().items() if v in names})
    rig.set_mapping(mapping)
    rig.is_mixamo = report["is_mixamo"]
    sx, sy, sz = arm.matrix_world.to_scale()
    if max(sx, sy, sz) - min(sx, sy, sz) > 1e-3 * max(sx, sy, sz):
        op.report({'WARNING'}, "El armature tiene escala no uniforme; aplícala (Ctrl+A) para mejores "
                                "resultados.")
    if report["missing_required"]:
        op.report({'WARNING'}, f"Faltan {len(report['missing_required'])} huesos obligatorios: "
                               "asígnalos a mano en «Mapeo de huesos».")
    else:
        kind = "Mixamo" if report["is_mixamo"] else "humanoide"
        op.report({'INFO'}, f"Rig {kind} detectado: {report['mapped']} de {report['total_slots']} "
                            "huesos mapeados.")
    return report


class AIMOCAP_OT_use_active(Operator):
    bl_idname = "ai_mocap.use_active"
    bl_label = "Usar selección"
    bl_description = "Usa como personaje el armature seleccionado (o el de la malla seleccionada)"

    def execute(self, context):
        arm = find_armature(context.active_object)
        if arm is None:
            self.report({'ERROR'}, "Selecciona un armature o una malla con modificador Armature.")
            return {'CANCELLED'}
        context.scene.ai_mocap.target = arm
        if not arm.data.ai_mocap.analyzed:
            _analyze(self, arm)
        return {'FINISHED'}


class AIMOCAP_OT_analyze_rig(Operator):
    bl_idname = "ai_mocap.analyze_rig"
    bl_label = "Detectar huesos"
    bl_description = "Detecta automáticamente los huesos del personaje (Mixamo y rigs humanoides comunes)"
    bl_options = {'REGISTER', 'UNDO'}
    keep_manual: BoolProperty(name="Conservar asignaciones manuales", default=False)

    def execute(self, context):
        arm = generation.resolve_target(context)
        if arm is None:
            self.report({'ERROR'}, "Elige primero el personaje.")
            return {'CANCELLED'}
        _analyze(self, arm, self.keep_manual)
        return {'FINISHED'}


class AIMOCAP_OT_assign_active_bone(Operator):
    bl_idname = "ai_mocap.assign_active_bone"
    bl_label = "Asignar hueso activo"
    bl_description = "Asigna a esta parte del cuerpo el hueso activo (selecciónalo en Pose o Edición)"
    bl_options = {'REGISTER', 'UNDO'}
    slot: StringProperty()

    def execute(self, context):
        arm = generation.resolve_target(context)
        bone = context.active_bone
        if arm is None or bone is None or bone.name not in arm.data.bones:
            self.report({'ERROR'}, "Selecciona un hueso del personaje.")
            return {'CANCELLED'}
        for item in arm.data.ai_mocap.slots:
            if item.slot == self.slot:
                item.bone = bone.name
        return {'FINISHED'}


_preset_items_cache = []


def _preset_items(_self, context):
    _preset_items_cache.clear()
    user_dir = common.paths(context).presets
    for pid, name, _path, builtin in P.list_presets(user_dir):
        _preset_items_cache.append((pid, name + ("" if builtin else " (usuario)"), ""))
    if not _preset_items_cache:
        _preset_items_cache.append(("NONE", "Sin presets", ""))
    return _preset_items_cache


class AIMOCAP_OT_preset_load(Operator):
    bl_idname = "ai_mocap.preset_load"
    bl_label = "Cargar preset de mapeo"
    bl_description = "Aplica un mapeo de huesos guardado"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "preset"
    preset: EnumProperty(name="Preset", items=_preset_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        arm = generation.resolve_target(context)
        if arm is None:
            self.report({'ERROR'}, "Elige primero el personaje.")
            return {'CANCELLED'}
        found = [p for p in P.list_presets(common.paths(context).presets) if p[0] == self.preset]
        if not found:
            return {'CANCELLED'}
        try:
            preset_map = P.load_preset(found[0][2])
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, f"Preset no válido: {exc}")
            return {'CANCELLED'}
        mapping, unmatched = P.resolve(preset_map, [b.name for b in arm.data.bones])
        rig = arm.data.ai_mocap
        rig.set_mapping(mapping)
        msg = f"Preset «{found[0][1]}» aplicado: {len(mapping)} huesos."
        if unmatched:
            msg += f" {len(unmatched)} no encontrados en este personaje."
        self.report({'WARNING' if rig.missing_required(arm.data) else 'INFO'}, msg)
        return {'FINISHED'}


class AIMOCAP_OT_preset_save(Operator):
    bl_idname = "ai_mocap.preset_save"
    bl_label = "Guardar preset de mapeo"
    bl_description = "Guarda el mapeo actual para reutilizarlo con otros personajes del mismo tipo"
    name: StringProperty(name="Nombre", default="Mi rig")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm = generation.resolve_target(context)
        if arm is None or not arm.data.ai_mocap.mapping():
            self.report({'ERROR'}, "No hay mapeo que guardar.")
            return {'CANCELLED'}
        path = P.save_preset(common.paths(context).presets, self.name.strip() or "preset",
                             arm.data.ai_mocap.mapping())
        self.report({'INFO'}, "Preset guardado: " + os.path.basename(path))
        return {'FINISHED'}


# --- B · Video ----------------------------------------------------------------

def _probe_with_blender(path):
    """Fallback when the engine is not installed: Blender's own movie reader."""
    clip = bpy.data.movieclips.load(path, check_existing=False)
    try:
        w, h = clip.size
        fps = clip.fps or 0.0
        frames = clip.frame_duration
        if not w or not frames:
            raise GenerateError("Blender no puede leer este vídeo.")
        return {"width": int(w), "height": int(h), "fps": float(fps), "frame_count": int(frames),
                "duration": frames / fps if fps else 0.0, "orientation_meta": 0, "path": path,
                "reader": "blender"}
    finally:
        bpy.data.movieclips.remove(clip)


def _store_video_info(scene_name, info):
    sc = bpy.data.scenes.get(scene_name)
    if sc is None:
        return
    s = sc.ai_mocap
    s["video_ok"] = True        # direct write: skips the update that resets the info
    s["video_info"] = json.dumps(info)
    if s.trim_end <= s.trim_start or s.trim_end > info.get("duration", 0) > 0:
        s.trim_end = round(info.get("duration", 0.0), 2)


class AIMOCAP_OT_probe_video(Operator):
    bl_idname = "ai_mocap.probe_video"
    bl_label = "Analizar vídeo"
    bl_description = "Lee la resolución, los FPS y la duración del vídeo"

    def execute(self, context):
        s = context.scene.ai_mocap
        path = generation.video_path(s)
        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, "El archivo de vídeo no existe.")
            return {'CANCELLED'}
        paths = common.paths(context)
        scene_name = context.scene.name
        if E.engine_state(paths)[0] != "READY":
            try:
                _store_video_info(scene_name, _probe_with_blender(path))
            except Exception as exc:
                self.report({'ERROR'}, f"No se pudo leer el vídeo: {exc}")
                return {'CANCELLED'}
            return {'FINISHED'}

        def done(task):
            if task.state == tasks.DONE:
                _store_video_info(scene_name, task.result)
        return _start_task(self, "Analizando vídeo", "probe",
                           lambda ctx: workers.probe_video(ctx, paths, path), done, context)


class AIMOCAP_OT_trim_to_current(Operator):
    bl_idname = "ai_mocap.trim_set"
    bl_label = "Ajustar recorte"
    bl_description = "Usa todo el vídeo como rango de recorte"

    def execute(self, context):
        s = context.scene.ai_mocap
        info = s.video_info_dict()
        s.trim_start = 0.0
        s.trim_end = round(info.get("duration", s.trim_end), 2)
        return {'FINISHED'}


# --- C · Generate -----------------------------------------------------------

class AIMOCAP_OT_generate(Operator):
    bl_idname = "ai_mocap.generate"
    bl_label = "Generar animación"
    bl_description = ("Analiza el vídeo con IA (en segundo plano, sin bloquear Blender) y crea una "
                      "Action nueva y editable en el personaje")
    bl_options = {'REGISTER', 'UNDO'}
    preview: BoolProperty(name="Vista previa", default=False, options={'SKIP_SAVE'},
                          description="Procesar solo los primeros segundos para comprobar el resultado")

    def execute(self, context):
        try:
            kind, obj, report = generation.start_generation(context, preview=self.preview)
        except (GenerateError, tasks.TaskError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"No se pudo generar: {exc}")
            return {'CANCELLED'}
        if kind == "APPLIED":
            tasks.clear_last()
            self.report({'INFO'}, "Análisis reutilizado de la caché. " + generation.describe(report, obj))
        else:
            self.report({'INFO'}, "Procesando el vídeo en segundo plano…")
        common.redraw_all()
        return {'FINISHED'}


class AIMOCAP_OT_regenerate(Operator):
    bl_idname = "ai_mocap.regenerate"
    bl_label = "Regenerar sin IA"
    bl_description = ("Crea otra Action a partir del último análisis con los ajustes actuales de "
                      "retargeting y salida (tarda segundos, no vuelve a analizar el vídeo)")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            action, report = generation.regenerate(context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, generation.describe(report, action))
        return {'FINISHED'}


# --- F · Controls -------------------------------------------------------------

class AIMOCAP_OT_assign_action(Operator):
    bl_idname = "ai_mocap.assign_action"
    bl_label = "Usar esta animación"
    bl_description = "Asigna esta Action al personaje"
    bl_options = {'REGISTER', 'UNDO'}
    action: StringProperty()

    def execute(self, context):
        arm = generation.resolve_target(context)
        action = bpy.data.actions.get(self.action)
        if arm is None or action is None:
            return {'CANCELLED'}
        generation.assign_action(arm, action)
        meta = generation.action_meta(action)
        if meta.get("output", {}).get("set_scene_range"):
            start, end = action.frame_range
            context.scene.frame_start, context.scene.frame_end = int(start), int(round(end))
        return {'FINISHED'}


class AIMOCAP_OT_restore_original(Operator):
    bl_idname = "ai_mocap.restore_original"
    bl_label = "Restaurar animación original"
    bl_description = "Vuelve a asignar la Action que tenía el personaje antes de usar AI Mocap"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = generation.resolve_target(context)
        if arm is None:
            return {'CANCELLED'}
        name = arm.data.ai_mocap.original_action
        action = bpy.data.actions.get(name) if name else None
        ad = arm.animation_data or arm.animation_data_create()
        if action is None:
            ad.action = None
            for pb in arm.pose.bones:
                pb.matrix_basis.identity()
            self.report({'INFO'}, "El personaje no tenía animación: se ha quitado la Action.")
        else:
            generation.assign_action(arm, action)
        return {'FINISHED'}


class AIMOCAP_OT_push_nla(Operator):
    bl_idname = "ai_mocap.push_nla"
    bl_label = "Enviar al NLA"
    bl_description = "Mueve la Action actual a una pista NLA (para mezclar o encadenar animaciones)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = generation.resolve_target(context)
        ad = arm.animation_data if arm else None
        if ad is None or ad.action is None:
            self.report({'ERROR'}, "El personaje no tiene ninguna Action asignada.")
            return {'CANCELLED'}
        generation.push_to_nla(arm, ad.action)
        return {'FINISHED'}


class AIMOCAP_OT_delete_action(Operator):
    bl_idname = "ai_mocap.delete_action"
    bl_label = "Eliminar animación"
    bl_description = "Elimina esta Action generada del archivo"
    bl_options = {'REGISTER', 'UNDO'}
    action: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Eliminar animación", message=f"Se eliminará «{self.action}».",
            confirm_text="Eliminar")

    def execute(self, context):
        action = bpy.data.actions.get(self.action)
        if action is None or generation.ACTION_TAG not in action.keys():
            return {'CANCELLED'}
        bpy.data.actions.remove(action)
        return {'FINISHED'}


class AIMOCAP_OT_toggle_rest(Operator):
    bl_idname = "ai_mocap.toggle_rest"
    bl_label = "Pose de reposo"
    bl_description = "Alterna entre la pose animada y la pose de reposo del personaje"

    def execute(self, context):
        arm = generation.resolve_target(context)
        if arm is None:
            return {'CANCELLED'}
        data = arm.data
        data.pose_position = 'POSE' if data.pose_position == 'REST' else 'REST'
        return {'FINISHED'}


classes = (
    AIMOCAP_OT_install_engine, AIMOCAP_OT_verify_engine, AIMOCAP_OT_download_model,
    AIMOCAP_OT_remove_engine, AIMOCAP_OT_clear_cache, AIMOCAP_OT_cancel_task,
    AIMOCAP_OT_dismiss_task, AIMOCAP_OT_open_path,
    AIMOCAP_OT_use_active, AIMOCAP_OT_analyze_rig, AIMOCAP_OT_assign_active_bone,
    AIMOCAP_OT_preset_load, AIMOCAP_OT_preset_save,
    AIMOCAP_OT_probe_video, AIMOCAP_OT_trim_to_current,
    AIMOCAP_OT_generate, AIMOCAP_OT_regenerate,
    AIMOCAP_OT_assign_action, AIMOCAP_OT_restore_original, AIMOCAP_OT_push_nla,
    AIMOCAP_OT_delete_action, AIMOCAP_OT_toggle_rest,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
