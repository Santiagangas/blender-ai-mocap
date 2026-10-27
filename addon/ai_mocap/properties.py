"""Settings saved in the .blend: per scene (video, processing, output) and per
armature (bone mapping, original action)."""

import json

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

from . import engine_env as E
from .rig.mapping import REQUIRED, SLOTS

SLOT_LABELS = {
    "hips": "Cadera", "spine": "Columna", "spine1": "Columna 1", "spine2": "Columna 2 (pecho)",
    "neck": "Cuello", "head": "Cabeza",
    "shoulder.L": "Clavícula I", "upper_arm.L": "Brazo I", "forearm.L": "Antebrazo I",
    "hand.L": "Mano I",
    "shoulder.R": "Clavícula D", "upper_arm.R": "Brazo D", "forearm.R": "Antebrazo D",
    "hand.R": "Mano D",
    "thigh.L": "Muslo I", "shin.L": "Pierna I", "foot.L": "Pie I", "toe.L": "Dedos pie I",
    "thigh.R": "Muslo D", "shin.R": "Pierna D", "foot.R": "Pie D", "toe.R": "Dedos pie D",
    "toe_end.L": "Punta pie I", "toe_end.R": "Punta pie D",
    "index1.L": "Índice I", "index1.R": "Índice D",
    "pinky1.L": "Meñique I", "pinky1.R": "Meñique D",
}


class AIMOCAP_PG_slot(PropertyGroup):
    slot: StringProperty(name="Ranura")
    bone: StringProperty(name="Hueso", description="Hueso del personaje que corresponde a esta parte "
                                                   "del cuerpo")


class AIMOCAP_PG_rig(PropertyGroup):
    """Stored on the Armature data, so the mapping travels with the character."""
    slots: CollectionProperty(type=AIMOCAP_PG_slot)
    analyzed: BoolProperty(default=False)
    is_mixamo: BoolProperty(default=False)
    original_action: StringProperty(
        description="Action que tenía el personaje antes de la primera generación")
    show_optional: BoolProperty(name="Huesos opcionales", default=False,
                                description="Mostrar también los huesos opcionales del mapeo")

    def mapping(self):
        return {i.slot: i.bone for i in self.slots if i.bone}

    def set_mapping(self, mapping):
        self.slots.clear()
        for slot in SLOTS:
            item = self.slots.add()
            item.slot = slot
            item.bone = mapping.get(slot, "")
        self.analyzed = True

    def missing_required(self, arm_data=None):
        m = self.mapping()
        bones = arm_data.bones if arm_data is not None else None
        return [s for s in REQUIRED if not m.get(s) or (bones is not None and m[s] not in bones)]


def _poll_armature(_self, obj):
    return obj.type == 'ARMATURE'


def _video_changed(self, _context):
    self.video_ok = False
    self.video_info = ""


VARIANT_ITEMS = [(k, v["label"], "Modelo MediaPipe Pose Landmarker " + k)
                 for k, v in E.MODELS.items()]


class AIMOCAP_PG_scene(PropertyGroup):
    # A · Personaje
    target: PointerProperty(name="Personaje", type=bpy.types.Object, poll=_poll_armature,
                            description="Armature que recibirá la animación")

    # B · Vídeo
    video_path: StringProperty(name="Vídeo", subtype='FILE_PATH', update=_video_changed,
                               description="Vídeo de referencia (MP4, MOV, AVI, MKV, WEBM…)")
    video_ok: BoolProperty(default=False)
    video_info: StringProperty(default="", description="Datos del vídeo analizado (JSON)")
    use_trim: BoolProperty(name="Recortar", default=False,
                           description="Procesar solo una parte del vídeo")
    trim_start: FloatProperty(name="Inicio", min=0.0, default=0.0, unit='TIME_ABSOLUTE',
                              description="Segundo del vídeo en el que empieza la captura")
    trim_end: FloatProperty(name="Fin", min=0.0, default=5.0, unit='TIME_ABSOLUTE',
                            description="Segundo del vídeo en el que termina la captura")
    rotation: EnumProperty(name="Rotación", default='0', items=[
        ('0', "0°", "Sin rotación adicional"),
        ('90', "90°", "Girar 90° en sentido horario"),
        ('180', "180°", "Girar 180°"),
        ('270', "270°", "Girar 90° en sentido antihorario")],
        description="Rotación extra si el vídeo aparece tumbado (la del móvil se aplica sola)")
    mirror: BoolProperty(name="Vídeo en espejo (selfie)", default=False,
                         description="Actívalo si el vídeo está grabado en modo espejo, para que "
                                     "izquierda y derecha sean las reales")

    # C · Procesamiento
    model_variant: EnumProperty(name="Modelo", items=VARIANT_ITEMS, default="full",
                                description="Modelo de detección de poses")
    fps_mode: EnumProperty(name="FPS", default='SCENE', items=[
        ('SCENE', "De la escena", "Muestrear el vídeo al FPS de la escena (un keyframe por fotograma)"),
        ('SOURCE', "Del vídeo", "Usar el FPS original del vídeo"),
        ('CUSTOM', "Personalizado", "Usar un FPS concreto")])
    custom_fps: FloatProperty(name="FPS", default=30.0, min=1.0, max=240.0)
    smoothing: FloatProperty(name="Suavizado", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
                             description="Más alto = menos temblor, pero movimientos rápidos más suaves")
    min_confidence: FloatProperty(name="Confianza mínima", default=0.5, min=0.05, max=0.95,
                                  subtype='FACTOR',
                                  description="Por debajo de este valor una articulación se considera "
                                              "oculta y se interpola")
    hfov: FloatProperty(name="Campo de visión", default=60.0, min=10.0, max=150.0,
                        description="Campo de visión horizontal aproximado de la cámara, en grados "
                                    "(60 = móvil o webcam típicos)")
    assume_upright: BoolProperty(name="Persona de pie", default=True,
                                 description="Descartar detecciones boca abajo. Desactívalo para "
                                             "vídeos con el cuerpo invertido (pino, volteretas)")
    initial_facing: EnumProperty(name="Orientación inicial", default='CAMERA', items=[
        ('CAMERA', "Mirando a cámara", "La persona empieza mirando hacia la cámara"),
        ('AUTO', "Automática", "Decidir a partir del vídeo")])
    use_cache: BoolProperty(name="Reutilizar análisis", default=True,
                            description="Si el vídeo ya se analizó con estos ajustes, no repetir la IA")

    # D · Retargeting
    root_mode: EnumProperty(name="Desplazamiento", default='FULL', items=[
        ('FULL', "Completo", "La cadera se desplaza por la escena y sube y baja"),
        ('VERTICAL', "Solo vertical", "Animación en el sitio, conservando saltos y agachados"),
        ('NONE', "Ninguno", "Solo rotaciones, la cadera no se mueve")])
    root_scale: FloatProperty(name="Escala del recorrido", default=1.0, min=0.0, max=5.0,
                              description="Multiplica el desplazamiento horizontal")
    facing_offset: FloatProperty(name="Giro adicional", default=0.0, min=-180.0, max=180.0,
                                 description="Gira toda la animación alrededor del eje vertical (grados)")
    hand_weight: FloatProperty(name="Seguimiento de manos", default=0.7, min=0.0, max=1.0,
                               subtype='FACTOR',
                               description="0 = las manos siguen al antebrazo; 1 = orientación detectada")
    neck_share: FloatProperty(name="Reparto cuello/cabeza", default=0.5, min=0.0, max=1.0,
                              subtype='FACTOR',
                              description="Parte del giro de la cabeza que se lleva el cuello")
    head_pitch_offset: FloatProperty(name="Corrección de cabeza", default=12.0, min=-45.0, max=45.0,
                                     description="Inclinación de la cabeza considerada neutra (grados)")

    # E · Salida
    action_name: StringProperty(name="Nombre", default="",
                                description="Nombre de la Action. Vacío = «Mocap_<vídeo>»")
    frame_start_mode: EnumProperty(name="Empieza en", default='SCENE', items=[
        ('SCENE', "Inicio de escena", "Primer fotograma de la escena"),
        ('CURRENT', "Fotograma actual", "Fotograma actual de la línea de tiempo"),
        ('CUSTOM', "Personalizado", "Un fotograma concreto")])
    frame_start: IntProperty(name="Fotograma", default=1)
    set_scene_range: BoolProperty(name="Ajustar rango de la escena", default=True,
                                  description="Ajustar inicio y fin de la escena a la animación")
    key_step: IntProperty(name="Keyframe cada", default=1, min=1, max=10,
                          description="1 = un keyframe por fotograma (máxima fidelidad). Valores "
                                      "mayores dan curvas más ligeras y fáciles de editar")
    interpolation: EnumProperty(name="Interpolación", default='AUTO', items=[
        ('AUTO', "Automática", "Lineal con un keyframe por fotograma, Bézier si se reducen"),
        ('LINEAR', "Lineal", ""), ('BEZIER', "Bézier", ""), ('CONSTANT', "Constante", "")])
    push_to_nla: BoolProperty(name="Enviar al NLA", default=False,
                              description="Colocar la nueva Action como tira en el editor NLA")

    # Internal state
    last_result_dir: StringProperty(default="", options={'HIDDEN'})
    last_report: StringProperty(default="", options={'HIDDEN'})
    show_video_adv: BoolProperty(name="Avanzado", default=False)
    show_proc_adv: BoolProperty(name="Avanzado", default=False)
    show_retarget_adv: BoolProperty(name="Avanzado", default=False)

    def video_info_dict(self):
        try:
            return json.loads(self.video_info) if self.video_info else {}
        except ValueError:
            return {}

    def report_dict(self):
        try:
            return json.loads(self.last_report) if self.last_report else {}
        except ValueError:
            return {}


classes = (AIMOCAP_PG_slot, AIMOCAP_PG_rig, AIMOCAP_PG_scene)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ai_mocap = PointerProperty(type=AIMOCAP_PG_rig)
    bpy.types.Scene.ai_mocap = PointerProperty(type=AIMOCAP_PG_scene)


def unregister():
    del bpy.types.Scene.ai_mocap
    del bpy.types.Armature.ai_mocap
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
