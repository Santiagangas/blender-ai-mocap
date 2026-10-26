# Blender AI Motion Capture — Fase 1: Investigación y diseño

Fecha: 2026-10-26 · Estado: propuesta para aprobación antes de la Fase 2

---

## 1. Entorno analizado (datos medidos, no supuestos)

| Elemento | Resultado |
|---|---|
| SO | Windows 10 Pro 19045 |
| CPU / RAM | AMD Ryzen 7 5800H (8 núcleos) · 15,4 GB |
| GPU | AMD Radeon integrada — **sin CUDA** |
| Blender | **5.1.2** (`C:\Program Files\Blender Foundation\Blender 5.1`) |
| Python de Blender | **3.13.9**, incluye `venv`, `pip` y `numpy` |
| Python del sistema | No instalado |
| FFmpeg del sistema | No instalado |
| Git | Disponible |

**Prueba de viabilidad del motor (hecha):** se creó un `venv` aislado a partir del Python de Blender y se instaló
`mediapipe 1.1.1 + opencv-python 5.0 + numpy 2.5 + scipy`. Importa correctamente y expone `PoseLandmarker`.
Tamaño del entorno: ~467 MB (reducible con `opencv-python-headless` y quitando `scipy`).

**Modelos MediaPipe Pose Landmarker (descarga inicial, medido):**
lite 5,5 MB · full 9,0 MB · heavy 29,2 MB.

### Personaje de referencia: `X Bot.fbx`

- Armature `Armature` con **65 huesos**, prefijo `mixamorig:`; meshes `Beta_Joints` y `Beta_Surface` con modificador Armature.
- Importación FBX típica de Mixamo: objeto con **escala 0,01 y rotación X 90°**. El retargeting debe trabajar
  en espacio del armature/mundo usando `matrix_world`; no puede suponer escala 1.
- Personaje mirando a **−Y** (los dedos de los pies están en Y negativo), altura ~1,83 m (HeadTop_End).
- Pose de reposo: **T-pose** (brazos en ±X horizontales).
- Acción existente `Armature|mixamo.com|Layer0` de 1 frame. Debe conservarse.
- **Blender 5.1 ya no tiene `Action.fcurves`** (comprobado: `hasattr(action, "fcurves") == False`). Las acciones son
  *slotted/layered*: las F-Curves se crean en `action.layers[].strips[].channelbag(slot)`. Esto condiciona todo el
  código de generación de keyframes.
- Riesgo detectado: Blender no abre scripts pasados con rutas cortas 8.3 (`SANTIM~1`). El addon resolverá siempre la
  ruta larga (`os.path.realpath`) antes de lanzar subprocesos.

---

## 2. Versión objetivo de Blender

- **Objetivo principal: Blender 5.1** (instalada y verificada aquí).
- **Mínimo declarado: 4.4**, primera versión con *slotted actions*. Usaremos `bpy_extras.anim_utils`
  (`action_ensure_channelbag_for_slot`) con una capa de compatibilidad propia. Solo se probará en 5.1; en 4.4–5.0
  quedará marcado como “no verificado”.
- Formato: **Extensión de Blender** (`blender_manifest.toml`), instalable con *Install from Disk* desde un ZIP.
  Declara los permisos `files` (leer vídeos) y `network` (descarga única del motor y del modelo).

---

## 3. Comparativa de métodos de estimación de pose

| Opción | Salida | Licencia | Instalación en esta máquina | Rendimiento (CPU) | Veredicto |
|---|---|---|---|---|---|
| **MediaPipe Pose Landmarker** (lite/full/heavy) | 33 puntos 2D + **world landmarks 3D en metros** (centro en la cadera), visibilidad por punto, talones y punta del pie | Apache-2.0 (código y modelos) | ✅ verificada (wheel `py3-none`) | Tiempo real o casi en lite/full; heavy unas cuantas veces más lento (se medirá en la Fase 2) | **Elegida como backend por defecto** |
| RTMPose / **RTMW3D** vía `rtmlib` (ONNX Runtime) | 133 puntos 3D (cuerpo, **manos y cara**) | Apache-2.0 | Probable (onnxruntime + opencv), sin torch | Más lento que MediaPipe; requiere detector de personas | **Segundo backend opcional** (Fase 4) para manos y dedos |
| MMPose completo | Muchos modelos 2D/3D | Apache-2.0 | ❌ PyTorch + mmcv en Windows: frágil | Lento sin GPU | Descartada como requisito |
| MotionBERT (*lifting* 2D→3D temporal) | Esqueleto H36M de 17 puntos, más estable en profundidad | Apache-2.0 | PyTorch CPU (~200 MB o más) | Aceptable en lotes | **Mejora opcional** para profundidad y temblor si MediaPipe no basta |
| WHAM / GVHMR / TRAM / 4DHumans (recuperación de malla SMPL con trayectoria global) | Rotaciones SMPL y trayectoria en el mundo: la mejor calidad | Código abierto, pero **el modelo SMPL es de uso no comercial** | ❌ requieren CUDA en la práctica | Inviable en GPU AMD integrada | **Descartadas como requisito**; se documentan como backend futuro |

**Justificación de la elección.** MediaPipe es la única opción que cumple a la vez cinco condiciones: instalación verificada
sin GPU, licencia permisiva, salida 3D métrica por frame, visibilidad por articulación y un tamaño pequeño. Sus carencias
(ver §6) se compensan con el pipeline temporal y el retargeting. El motor tendrá una interfaz `PoseBackend` para añadir
RTMW3D o MotionBERT sin cambiar el addon.

---

## 4. Arquitectura

```
┌────────────────────────── Blender (bpy, Python 3.13) ──────────────────────────┐
│  UI (paneles A–F) → Operadores → JobManager (operador modal + timer)          │
│        │                               ▲  progreso (JSON lines por stdout)     │
│        ▼                               │                                       │
│  rig/       detección, validación y mapeo de huesos                            │
│  retarget/  landmarks → rotaciones locales (cuaterniones, numpy + mathutils)   │
│  anim/      creación de Action, slot, channelbag, F-Curves (foreach_set)       │
└────────│───────────────────────────────▲───────────────────────────────────────┘
         │ subprocess: job.json           │ result.json + motion.npz (caché)
┌────────▼───────────────────────────────│───────────── venv aislado ─────────────┐
│  engine/  video I/O (OpenCV) → PoseBackend (MediaPipe) → tracking temporal     │
│           → relleno de huecos → filtrado → normalización de huesos → contrato  │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Por qué un proceso separado aunque MediaPipe importe en Python 3.13:**
1. No se instalan paquetes en el Python de Blender, como pide el proyecto.
2. Si el modelo falla (memoria, DLL, vídeo corrupto), el proceso muere solo y Blender y el `.blend` quedan intactos.
3. La cancelación es fiable: se termina el proceso.
4. La interfaz no se bloquea. Un hilo lector vuelca stdout a una cola y un temporizador modal la consume. **Ninguna
   llamada `bpy` se hace desde hilos.**
5. Se pueden cambiar las versiones del motor sin tocar Blender.

**Separación de tiempos.** El procesamiento de IA ocurre en el motor y su resultado se guarda en caché. La generación de
keyframes ocurre en Blender y tarda segundos. Por eso se pueden regenerar animaciones con otros ajustes de retargeting o
suavizado final sin volver a analizar el vídeo.

### Contrato de datos v1

- `job.json` (addon → motor): `contract_version`, ruta del vídeo, `trim_start`/`trim_end`, `target_fps`, `backend`,
  `model_variant`, opciones de filtrado, `rotate` (0/90/180/270), `mirror`.
- `progress` (stdout, una línea JSON por evento): `{"type":"progress","stage":"pose","done":120,"total":900}`,
  `{"type":"error","code":"VIDEO_UNREADABLE","message":"..."}`, `{"type":"done"}`.
- `result.json`: `contract_version`, `coordinate_system` (`"right-handed, +Z up, +Y forward(subject facing -Y), meters"`),
  `fps`, `frame_count`, `source` (resolución, fps, duración, orientación), `joint_names`, `backend` (nombre, versión,
  modelo, hash), estadísticas de calidad (porcentaje de frames detectados y huecos rellenados).
- `motion.npz` (sin pickle, `allow_pickle=False`, float32):
  `world[F,J,3]` (3D métrico relativo a la pelvis) · `image[F,J,2]` (normalizado) · `confidence[F,J]` ·
  `root[F,3]` (trayectoria estimada de la pelvis) · `valid[F]` (bool) · `interpolated[F,J]` (bool).

Se elige NPZ para las secuencias porque es compacto, rápido y lo lee el `numpy` que ya trae Blender. JSON solo se usa para
metadatos legibles.
Caché: `<config de usuario>/ai_mocap/cache/<sha1(ruta+tamaño+mtime+parámetros del motor)>/`.

---

## 5. Pipeline de reconstrucción y retargeting

### Motor (por vídeo)
1. Lectura con OpenCV respetando la orientación (`CAP_PROP_ORIENTATION_AUTO`), recorte y remuestreo al FPS de salida.
2. `PoseLandmarker` en modo `VIDEO` (usa el seguimiento temporal interno), por lotes de frames, sin guardar todo el vídeo en memoria.
3. Huecos: las articulaciones con visibilidad inferior al umbral se marcan; los huecos cortos se interpolan (spline) y los
   largos mantienen la última pose con un paso suave a la siguiente pose válida.
4. Filtrado: **One-Euro** (adaptativo, elimina el temblor sin añadir retraso en movimientos rápidos) y, opcionalmente,
   **Butterworth de fase cero** (el vídeo completo está disponible, así que no hay restricción de causalidad).
5. Normalización de la longitud de los huesos (mediana a lo largo de la secuencia) para que las extremidades no se estiren.
6. Trayectoria raíz: los world landmarks están centrados en la cadera, así que el desplazamiento se estima a partir de la
   pelvis 2D más la escala aparente del torso (profundidad aproximada) y se ancla al suelo con el pie más bajo.

### Retargeting (en Blender)
- **Mapeo:** perfil Mixamo predefinido más heurística (se quita el prefijo `mixamorig\d*:`, sinónimos como `UpperArm`,
  `Thigh` o `Calf`, lados `Left`/`L_`/`.L`/`_l`). Diagnóstico de cobertura. Si falta algún hueso principal, aparece un
  panel de mapeo manual que se guarda en el armature (propiedad personalizada) y como preset JSON reutilizable.
- **Método basado en direcciones y marcos, no en posiciones:** para cada hueso mapeado se construye una orientación
  objetivo en espacio del armature: eje Y del hueso = dirección del segmento (p. ej. hombro→codo); eje de giro
  (*twist*) = vector secundario (normal del plano hombro-codo-muñeca, eje izquierda-derecha de la pelvis o del pecho).
  La diferencia con el marco equivalente en la pose de reposo (T-pose) da la rotación delta. Así se tienen en cuenta
  el *roll* de cada hueso, la escala 0,01 y la rotación de 90°.
- **Jerarquía:** se recorre de raíz a hojas; `local = (M_padre_pose · M_offset_reposo)⁻¹ · M_objetivo`, con cuaterniones.
- **Continuidad:** se invierte el signo del cuaternión cuando `q·q_prev < 0` (evita giros de 360°) y se limita el *twist*
  del antebrazo para evitar torsiones.
- **Columna:** MediaPipe solo da hombros y caderas, así que la rotación pelvis→pecho se reparte entre Spine/Spine1/Spine2 (≈30/30/40 %).
- **Raíz:** traslación de Hips escalada por la relación entre la longitud de pierna del personaje y la de la persona,
  con opciones Ninguna / Solo vertical / Completa.
- **Escritura:** Action nueva (nunca se sobrescribe sin confirmación), slot propio, F-Curves rellenadas con
  `keyframe_points.foreach_set` (mucho más rápido que `keyframe_insert`), reducción opcional de keyframes, ajuste del
  rango de la escena, `use_fake_user` para que la acción se conserve en el `.blend`.

---

## 6. Limitaciones honestas (se mostrarán también en la documentación)

| Aspecto | Qué es posible con MediaPipe y una cámara | Mejora viable |
|---|---|---|
| Profundidad | Ambigua: los movimientos hacia la cámara o desde ella se estiman con error mayor que los laterales | MotionBERT (lifting temporal); grabar en ángulo de ¾ |
| Trayectoria global | Aproximada; sin cámara calibrada, la escala y la distancia se deducen | Opción de fijar la raíz; backend tipo WHAM/GVHMR con GPU NVIDIA |
| Columna | Un solo segmento real (caderas→hombros); la curvatura se reparte | — |
| Cabeza / cuello | Orientación aproximada a partir de nariz, ojos y orejas | — |
| Manos | Solo muñeca, índice, meñique y pulgar → orientación de la mano aproximada; **sin dedos** | RTMW3D (133 puntos) o MediaPipe Hand Landmarker |
| Pies | Talón y punta del pie → orientación razonable; puede haber deslizamiento | Bloqueo de contacto con el suelo (Fase 4) |
| Oclusiones | Se interpolan; las oclusiones largas producen poses inventadas y suavizadas, no reales | Avisos en el informe de calidad |
| Varias personas | Se sigue a una persona (la más grande o centrada) | — |
| Rendimiento | Sin GPU compatible: CPU. No se promete tiempo real con el modelo heavy | Variantes lite/full |

---

## 7. Riesgos técnicos principales

1. **API de Actions en Blender 5.x** (slots, layers, channelbags): mitigado con un módulo `anim/compat.py` y pruebas en background.
2. **Orientación y *roll* de los huesos** al pasar de espacio de captura a espacio local: mitigado con pruebas unitarias
   de ida y vuelta (pose conocida → landmarks sintéticos → retargeting → misma pose).
3. **Calidad de MediaPipe en profundidad y oclusiones**: mitigado con filtrado, informe de calidad y backends alternativos.
4. **Instalación en equipos de usuarios** (red, antivirus, rutas con espacios o 8.3, ~250–470 MB): el instalador hace
   comprobaciones, usa versiones fijadas y una autoprueba, y muestra mensajes claros.
5. **Vídeos de prueba con licencia**: se propone un **test de bucle cerrado**. Se anima el X Bot con keyframes conocidos,
   se renderiza un vídeo desde Blender, se procesa y se compara el ángulo de cada articulación con la verdad conocida.
   Es reproducible y no tiene problemas de licencia. Riesgo: MediaPipe podría detectar peor a un robot que a una persona;
   en ese caso se usará un vídeo real proporcionado por el usuario o un vídeo CC0.

---

## 8. Estructura de carpetas propuesta

```
blender-ai-mocap/
├─ addon/ai_mocap/                 # extensión de Blender (se empaqueta en el ZIP)
│  ├─ blender_manifest.toml
│  ├─ __init__.py                  # registro
│  ├─ preferences.py               # instalación y verificación del motor
│  ├─ properties.py                # PropertyGroups (escena / armature)
│  ├─ ui/panels.py                 # A Character · B Video · C Processing · D Retarget · E Output · F Controls
│  ├─ operators/                   # analyze_rig, analyze_video, generate, cancel, preview, clear, mapping
│  ├─ core/job_manager.py          # subprocess + hilo lector + timer modal
│  ├─ core/contract.py             # versión y validación del contrato
│  ├─ rig/{detect,mapping,profiles}.py
│  ├─ retarget/{frames,solver,smoothing}.py
│  ├─ anim/{compat,writer}.py
│  ├─ presets/mixamo.json
│  └─ engine_src/                  # código del motor, copiado al venv al instalar
├─ engine/ai_mocap_engine/
│  ├─ cli.py  video_io.py  backends/{base,mediapipe_backend}.py
│  ├─ temporal.py (huecos, One-Euro, Butterworth)  skeleton.py  root.py  contract.py
│  └─ requirements.lock
├─ tests/
│  ├─ unit/            # matemáticas puras (pytest en el venv del motor)
│  ├─ blender/         # blender -b --python ... (mapeo, retarget, Action, guardar/reabrir)
│  └─ e2e/             # bucle cerrado con vídeo renderizado
├─ tools/build_zip.py
└─ docs/ (es) INSTALACION.md · USO.md · PROBLEMAS_FRECUENTES.md · ARQUITECTURA.md
```

## 9. Instalación prevista

1. *Preferencias → Extensiones → Install from Disk* → `ai_mocap-x.y.z.zip`. El ZIP es solo Python, sin binarios.
2. En las preferencias del addon: **Install Motion Engine**. Crea un `venv` con el propio Python de Blender
   (`sys.executable -m venv`) dentro de la carpeta de usuario de la extensión, instala las dependencias fijadas e
   informa del progreso en la barra de estado.
3. **Download Model**: descarga `pose_landmarker_full` (9 MB) o `heavy` (29 MB), comprueba el hash y muestra el progreso.
4. **Verify**: ejecuta el motor con un autotest (versiones, carga del modelo, inferencia sobre una imagen sintética).
5. Todo ocurre en local; no se necesitan API keys ni procesamiento en la nube.

## 10. Plan inmediato — Fase 2 (prueba de viabilidad)

Objetivo: demostrar el flujo **vídeo → landmarks → retarget → Action reproducible** en el X Bot, sin interfaz completa:
1. Motor CLI mínimo (MediaPipe `full`, One-Euro y contrato v1).
2. Generar un vídeo de prueba (bucle cerrado renderizado desde Blender) y, si el usuario la aporta, una grabación real.
3. Script de Blender en background: importar X Bot → retarget → Action → guardar `.blend` → reabrir y comprobar los keyframes.
4. Informe con métricas: frames detectados, error angular por articulación en el bucle cerrado y tiempos de IA frente a keyframes.
