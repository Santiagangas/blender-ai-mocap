"""Sidebar panels (View3D → N → AI Mocap): A Personaje · B Vídeo · C Procesamiento ·
D Retargeting · E Salida · F Controles."""

import bpy
from bpy.types import Panel

from . import common
from . import engine_env as E
from .core import generation, tasks
from .prefs import STATE_TEXT, draw_task_box
from .properties import SLOT_LABELS
from .rig.mapping import REQUIRED, SLOTS


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI Mocap"


def _settings(context):
    return context.scene.ai_mocap


class AIMOCAP_PT_character(_Base, Panel):
    bl_label = "A · Personaje"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        s = _settings(context)
        row = layout.row(align=True)
        row.prop(s, "target", text="")
        row.operator("ai_mocap.use_active", text="", icon='EYEDROPPER')
        arm = generation.resolve_target(context)
        if arm is None:
            layout.label(text="Selecciona el personaje riggeado.", icon='INFO')
            return
        rig = arm.data.ai_mocap
        if s.target is None:
            layout.label(text=f"Se usará el seleccionado: {arm.name}", icon='INFO')
        if not rig.analyzed:
            layout.operator("ai_mocap.analyze_rig", icon='VIEWZOOM')
            return
        missing = rig.missing_required(arm.data)
        mapped = sum(1 for i in rig.slots if i.bone)
        box = layout.box()
        if missing:
            box.alert = True
            box.label(text=f"Faltan {len(missing)} huesos obligatorios", icon='ERROR')
        else:
            kind = "Mixamo" if rig.is_mixamo else "Humanoide"
            box.label(text=f"{kind} · {mapped}/{len(SLOTS)} huesos mapeados", icon='CHECKMARK')
        box.label(text=f"{len(arm.data.bones)} huesos en el armature", icon='BONE_DATA')
        row = layout.row(align=True)
        row.operator("ai_mocap.analyze_rig", text="Volver a detectar", icon='FILE_REFRESH')


class AIMOCAP_PT_mapping(_Base, Panel):
    bl_label = "Mapeo de huesos"
    bl_parent_id = "AIMOCAP_PT_character"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        arm = generation.resolve_target(context)
        return arm is not None and arm.data.ai_mocap.analyzed

    def draw(self, context):
        layout = self.layout
        arm = generation.resolve_target(context)
        rig = arm.data.ai_mocap
        row = layout.row(align=True)
        row.operator("ai_mocap.preset_load", text="Cargar preset", icon='PRESET')
        row.operator("ai_mocap.preset_save", text="Guardar", icon='ADD')
        layout.prop(rig, "show_optional")
        col = layout.column(align=True)
        for item in rig.slots:
            required = item.slot in REQUIRED
            if not required and not rig.show_optional:
                continue
            r = col.row(align=True)
            bad = required and (not item.bone or item.bone not in arm.data.bones)
            r.alert = bad
            label = SLOT_LABELS.get(item.slot, item.slot) + (" *" if required else "")
            r.prop_search(item, "bone", arm.data, "bones", text=label)
            r.operator("ai_mocap.assign_active_bone", text="", icon='RESTRICT_SELECT_OFF').slot = item.slot
        layout.label(text="* obligatorio", icon='BLANK1')


class AIMOCAP_PT_video(_Base, Panel):
    bl_label = "B · Vídeo"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        s = _settings(context)
        layout.prop(s, "video_path", text="")
        row = layout.row()
        row.enabled = bool(s.video_path) and not tasks.busy()
        row.operator("ai_mocap.probe_video", icon='FILE_MOVIE')
        info = s.video_info_dict() if s.video_ok else {}
        if info:
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"{info['width']} × {info['height']} · {info['fps']:.2f} FPS", icon='CHECKMARK')
            col.label(text=f"Duración: {info['duration']:.1f} s ({info['frame_count']} fotogramas)",
                      icon='BLANK1')
            if info.get("orientation_meta"):
                col.label(text=f"Rotación del móvil: {info['orientation_meta']}° (se aplica sola)",
                          icon='BLANK1')
        layout.prop(s, "use_trim")
        if s.use_trim:
            row = layout.row(align=True)
            row.prop(s, "trim_start")
            row.prop(s, "trim_end")
            if info:
                row.operator("ai_mocap.trim_set", text="", icon='FULLSCREEN_ENTER')
        layout.prop(s, "mirror")
        layout.prop(s, "show_video_adv", icon='TRIA_DOWN' if s.show_video_adv else 'TRIA_RIGHT',
                    emboss=False)
        if s.show_video_adv:
            layout.prop(s, "rotation")


class AIMOCAP_PT_processing(_Base, Panel):
    bl_label = "C · Procesamiento"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        s = _settings(context)
        paths = common.paths(context)
        state, detail = E.engine_state(paths)
        if state != "READY":
            box = layout.box()
            box.alert = True
            box.label(text="Motor de captura: " + STATE_TEXT[state], icon='ERROR')
            box.label(text="Instálalo en Preferencias → Complementos → AI Mocap.", icon='BLANK1')
            box.operator("preferences.addon_show", text="Abrir preferencias",
                         icon='PREFERENCES').module = common.PACKAGE

        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "model_variant")
        if not paths.model_ok(s.model_variant):
            col.label(text="Se descargará al generar", icon='IMPORT')
        col.prop(s, "fps_mode")
        if s.fps_mode == 'CUSTOM':
            col.prop(s, "custom_fps")
        col.prop(s, "smoothing", slider=True)
        layout.prop(s, "show_proc_adv", icon='TRIA_DOWN' if s.show_proc_adv else 'TRIA_RIGHT',
                    emboss=False)
        if s.show_proc_adv:
            col = layout.column()
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(s, "min_confidence", slider=True)
            col.prop(s, "hfov")
            col.prop(s, "initial_facing")
            col.prop(s, "assume_upright")
            col.prop(s, "use_cache")

        busy = tasks.busy()
        col = layout.column(align=True)
        col.scale_y = 1.6
        col.enabled = not busy
        col.operator("ai_mocap.generate", icon='ARMATURE_DATA').preview = False
        row = layout.row(align=True)
        row.enabled = not busy
        row.operator("ai_mocap.generate", text="Vista previa (3 s)", icon='PLAY').preview = True
        row.operator("ai_mocap.regenerate", icon='FILE_REFRESH')
        draw_task_box(layout, kinds={"capture", "probe", "model"})


class AIMOCAP_PT_retarget(_Base, Panel):
    bl_label = "D · Retargeting"
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = _settings(context)
        layout.prop(s, "root_mode")
        sub = layout.column()
        sub.active = s.root_mode == 'FULL'
        sub.prop(s, "root_scale")
        layout.prop(s, "facing_offset")
        layout.prop(s, "hand_weight", slider=True)
        layout.prop(s, "show_retarget_adv", emboss=False,
                    icon='TRIA_DOWN' if s.show_retarget_adv else 'TRIA_RIGHT')
        if s.show_retarget_adv:
            layout.prop(s, "neck_share", slider=True)
            layout.prop(s, "head_pitch_offset")
        layout.label(text="Cambia estos ajustes y pulsa «Regenerar sin IA».", icon='INFO')


class AIMOCAP_PT_output(_Base, Panel):
    bl_label = "E · Salida"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = _settings(context)
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "action_name")
        col.prop(s, "frame_start_mode")
        if s.frame_start_mode == 'CUSTOM':
            col.prop(s, "frame_start")
        col.prop(s, "key_step")
        col.prop(s, "interpolation")
        col.prop(s, "set_scene_range")
        col.prop(s, "push_to_nla")

        rep = s.report_dict()
        if rep:
            box = layout.box()
            box.label(text="Última animación generada", icon='ACTION')
            c = box.column(align=True)
            c.label(text=f"«{rep['action']}» en {rep['armature']}")
            c.label(text=f"Fotogramas {rep['frame_start']}–{rep['frame_end']} · {rep['bones']} huesos · "
                         f"{rep['keys']} keys por curva")
            c.label(text=f"Persona detectada en el {rep['detected']} % del vídeo",
                     icon='CHECKMARK' if rep['detected'] >= 90 else 'ERROR')
            if rep.get("never_seen"):
                c.label(text="No vistas nunca: " + ", ".join(rep["never_seen"][:4]), icon='ERROR')
            t = rep.get("engine_s")
            c.label(text=(f"IA: {t:.1f} s · " if t else "") +
                         f"Keyframes: {rep['solve_s'] + rep['write_s']:.2f} s")


class AIMOCAP_PT_controls(_Base, Panel):
    bl_label = "F · Controles"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        screen = context.screen
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("screen.frame_jump", text="", icon='REW').end = False
        playing = bool(screen and screen.is_animation_playing)
        row.operator("screen.animation_play", text="Pausa" if playing else "Reproducir",
                     icon='PAUSE' if playing else 'PLAY')
        row.operator("screen.frame_jump", text="", icon='FF').end = True
        layout.prop(context.scene, "frame_current")

        arm = generation.resolve_target(context)
        if arm is None:
            return
        rest = arm.data.pose_position == 'REST'
        row = layout.row(align=True)
        row.operator("ai_mocap.toggle_rest", text="Ver animación" if rest else "Ver pose de reposo",
                     icon='ARMATURE_DATA' if rest else 'OUTLINER_OB_ARMATURE', depress=rest)
        row.operator("ai_mocap.push_nla", icon='NLA')

        ad = arm.animation_data
        current = ad.action if ad else None
        actions = generation.generated_actions()
        box = layout.box()
        box.label(text="Animaciones generadas", icon='ACTION')
        if not actions:
            box.label(text="Todavía no hay ninguna.", icon='BLANK1')
        for action in actions:
            r = box.row(align=True)
            is_current = action == current
            op = r.operator("ai_mocap.assign_action", text=action.name,
                            icon='RADIOBUT_ON' if is_current else 'RADIOBUT_OFF', depress=is_current)
            op.action = action.name
            r.operator("ai_mocap.delete_action", text="", icon='TRASH').action = action.name
        if arm.data.ai_mocap.original_action or actions:
            layout.operator("ai_mocap.restore_original", icon='LOOP_BACK')
        layout.label(text="Edita los keyframes en el Dope Sheet o el Graph Editor.", icon='INFO')


classes = (AIMOCAP_PT_character, AIMOCAP_PT_mapping, AIMOCAP_PT_video, AIMOCAP_PT_processing,
           AIMOCAP_PT_retarget, AIMOCAP_PT_output, AIMOCAP_PT_controls)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
