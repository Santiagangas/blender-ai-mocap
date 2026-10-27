# Blender AI Motion Capture — Fase 3: addon instalable con interfaz completa

Fecha: 2026-10-27 · Blender 5.1.2 · MediaPipe 1.1.1 · Estado: **completada** (pendiente de probar la interfaz en
Windows con Blender real, ver §5)

---

## 1. Qué se ha construido

El prototipo de la Fase 2 (scripts en línea de comandos) pasa a ser una **extensión de Blender instalable**:

- **Instalación desde un ZIP** de 61 KB (*Instalar desde disco*). Validado con el validador oficial de extensiones de
  Blender e instalado y desinstalado con su gestor de paquetes.
- **Instalador del motor en las preferencias:** crea un entorno aislado con el Python de Blender, instala las
  dependencias con versiones fijadas, descarga el modelo comprobando su SHA-256 y hace una autoprueba. Hay botones
  para verificar, reinstalar, eliminar y descargar los otros modelos. Respeta la opción de Blender *Permitir acceso en
  línea*.
- **Seis paneles** en la barra lateral del Visor 3D (pestaña *AI Mocap*): A Personaje (con subpanel de mapeo),
  B Vídeo, C Procesamiento, D Retargeting, E Salida y F Controles. Guía de uso en [USO.md](USO.md).
- **Procesamiento sin bloquear Blender:** la IA corre en un proceso aparte. Un hilo lee su progreso y un temporizador
  del hilo principal lo muestra en una barra con botón *Cancelar*. Ninguna llamada a `bpy` se hace fuera del hilo
  principal. Al cancelar se termina el proceso y el personaje no cambia.
- **Caché de análisis:** la clave combina el vídeo (ruta, tamaño y fecha), todos los ajustes que cambian el resultado,
  la versión del motor y la huella del modelo. Regenerar con otro retargeting o salida tarda menos de un segundo.
- **Mapeo manual** guardado en el armature, presets JSON (Mixamo incluido, más los del usuario) independientes del
  prefijo `mixamorig*:`, y botón para asignar el hueso activo.
- **Opciones de salida:** nombre, fotograma inicial, reducción de keyframes (1 de cada N, con Bézier), interpolación,
  ajuste del rango de la escena y envío al NLA.
- **Controles:** reproducción, pose de reposo, lista de animaciones generadas (asignar o eliminar) y restaurar la
  animación original. La Action original del personaje nunca se borra: se marca con *fake user*.
- **Metadatos** en cada Action generada (vídeo, fecha y ajustes) para saber de dónde salió.

## 2. Arquitectura del addon

```
addon/ai_mocap/
├─ blender_manifest.toml      extensión (permisos files + network), Blender ≥ 4.4
├─ __init__.py                registro; cancela la tarea al abrir otro archivo
├─ properties.py              ajustes por escena (Scene.ai_mocap) y mapeo por armature (Armature.ai_mocap)
├─ prefs.py                   preferencias: estado e instalación del motor, modelos, caché, carpeta de datos
├─ ui.py                      paneles A–F
├─ operators.py               22 operadores (botones)
├─ common.py / engine_env.py  rutas, versiones, entorno limpio de los subprocesos, estado del motor
├─ engine_requirements.txt    mediapipe==1.1.1, opencv-contrib-python==5.0.0.93, numpy==2.5.4
├─ presets/mixamo.json
├─ core/tasks.py              tareas en segundo plano: hilo + cola + temporizador, cancelación, registros
├─ core/workers.py            trabajo en segundo plano: instalar, descargar, verificar, analizar, capturar (sin bpy)
├─ core/generation.py         generar / regenerar en el hilo principal: caché → retargeting → Action
├─ core/cache.py · core/apply.py · core/contract.py
├─ rig/ (detect, mapping, presets) · retarget/ (solver, rotations) · anim/writer.py
└─ engine_src/                (solo en el ZIP) copia del motor; se ejecuta en su entorno, nunca dentro de Blender
```

`tools/build_zip.py` genera `dist/ai_mocap-<versión>.zip` con el manifiesto en la raíz y el motor en `engine_src/`.
En una copia de desarrollo, el addon usa directamente `engine/`.

## 3. Pruebas

| Prueba | Cómo se ejecuta | Resultado |
|---|---|---|
| Unitarias (matemáticas, mapeo, caché, presets, límite de rutas de Windows, tabla de modelos) | `pytest tests/unit` | **28/28** |
| Integración del addon (53 comprobaciones; 66 con el motor real) | `python tests/blender/test_addon.py` con `pip install bpy==5.1.2`, o `blender -b --python …` | **OK** |
| Igual, con motor real (`--engine --video clip.mp4`) | instala desde las preferencias, verifica y captura | **OK** |
| ZIP | validador oficial de extensiones + instalación y desinstalación con el gestor de Blender | **OK** |

La prueba de integración construye un X Bot de Mixamo a partir de la pose de reposo real guardada en
`tests/fixtures/xbot_rest.npz`, con la escala 0,01 y la rotación de 90° de una importación FBX. Después usa el addon
como un usuario:

- detecta el rig, borra un hueso, guarda y carga presets;
- genera la animación (desde caché y con la IA real) y prueba todas las opciones de salida;
- cambia, restaura, envía al NLA y elimina Actions;
- guarda y vuelve a abrir el `.blend`;
- prueba el sistema de tareas con procesos reales: progreso, errores, fallos inesperados y cancelación en menos de 1 s.

Además dibuja **todos los paneles y las preferencias** en siete estados distintos (ocho con el motor real) con una interfaz simulada estricta.
Esa interfaz falla si un panel usa una propiedad, un operador o un icono que no existen.

### Medidas con el motor real (CPU, contenedor Linux)

| Paso | Tiempo |
|---|---|
| Instalar el motor (con la caché de pip ya llena; la primera vez depende de la conexión, ~470 MB) | 19–36 s |
| Tamaño del entorno del motor | 518 MB |
| Vídeo real de 4,1 s (1280×720, 50 FPS) → 123 fotogramas a 30 FPS | **4,7 s** en total, la IA en segundo plano |
| Retargeting + keyframes | 0,02 s |
| Segunda generación con el mismo vídeo (caché) | 0,02 s |

### Primera prueba con una persona real

Se usó un vídeo de muestra público: una persona bailando en una calle concurrida, con más gente al fondo y un giro
completo. Por su licencia no se ha incluido en el repositorio. La persona se detectó en el 100 % de los fotogramas. Al
comparar la pose del personaje con el vídeo, los brazos abiertos, los pasos y el brazo levantado coinciden. Los
problemas observados confirman las limitaciones conocidas:

- **Altura al inicio:** con la persona lejos y en movimiento, el personaje empieza flotando unos 50 cm y se asienta
  en menos de un segundo. Hace falta fijar los pies al suelo (Fase 4).
- **Deriva en profundidad:** la trayectoria se desplaza ~1,4 m hacia la cámara en 4 s, más de lo real. La opción
  *Solo vertical* lo evita.
- En 26 de 123 fotogramas se corrigió la ambigüedad delante/detrás. Eso coincide con el giro de la persona.

Sigue pendiente una validación con un vídeo grabado a propósito: cuerpo entero, cámara fija y una sola persona.

## 4. Riesgos tratados en esta fase

- **Ruta máxima de Windows (260 caracteres):** el archivo más profundo del motor mide 101 caracteres dentro de
  `site-packages`. Con una ruta de usuario típica queda en ~244. El instalador lo comprueba antes de descargar nada y,
  si no cabe y Windows no tiene activadas las rutas largas, pide una carpeta más corta.
- **Linux sin librerías gráficas:** MediaPipe necesita `libEGL`. La autoprueba lo detecta y explica cómo instalarla.
- **Abrir otro archivo durante una captura:** la tarea se cancela y la carpeta temporal se limpia en la siguiente
  generación.
- **El personaje o la escena se borran durante la captura:** el análisis se guarda en caché y el mensaje indica que
  se puede aplicar con *Regenerar*.

## 5. Pendiente

1. **Probar en tu Windows con Blender 5.1.2:** instalar el ZIP, instalar el motor y generar con el X Bot. Aquí la
   interfaz se ha probado con Blender como módulo de Python y una interfaz simulada, no con la ventana real.
2. Validar con un vídeo propio de una persona (cuerpo entero, cámara fija).
3. **Fase 4:** fijar los pies al suelo, estabilizar la altura y la profundidad de la raíz, límites anatómicos, giro de
   los brazos por encima de la cabeza y suavizado mejorado.
4. **Fase 5:** empaquetado final, documentación con capturas y pruebas en 4.4–5.0.

## 6. Revisión 0.3.1 (tras las primeras pruebas en Windows)

**Bailes de perfil: brazos y piernas «rotos».** Con un vídeo de baile visto de lado («Dame tu cosita»), el
personaje salía con un brazo hacia atrás y las piernas cruzadas, aunque el informe decía «persona detectada en el
100 %». La causa estaba en el motor. El brazo y la pierna del lado tapado tenían una confianza muy baja (mediana 0,01
en el codo derecho), así que el motor los descartaba y rellenaba el hueco interpolando. El hueco más largo era de 49
fotogramas (1,6 s), y durante todo ese tiempo se congelaba la pose de otro momento del baile.

Corrección (motor 0.3.0): los huecos de baja confianza de hasta 0,25 s se siguen interpolando, porque suelen ser
destellos. En los más largos se usa la estimación que da MediaPipe para la parte tapada, que es mucho más verosímil.
Se puede ajustar en *Procesamiento → Avanzado → Interpolar huecos de hasta*.

| Mismo vídeo, modelo Heavy | Antes | Después |
|---|---|---|
| Codo / muñeca derechos inventados por interpolación | 68 % / 71 % | 1 % / 4 % |
| Rodilla / tobillo derechos inventados | 60 % / 45 % | 1 % / 4 % |
| Máximo inventado en cualquier punto (solo dedos y talones) | 74 % | 13 % |

Al comparar con el vídeo, las piernas pasan de salir juntas y cruzadas a flexionarse y abrirse como en el vídeo, y
los brazos estirados coinciden. Como cambia la versión del motor, la caché anterior no se reutiliza y el vídeo se
vuelve a analizar.

**Blender 4.4 y 4.5.** Esas versiones traen Python 3.11, y NumPy 2.5.4 solo existe para Python 3.12 o superior, así
que la instalación del motor fallaba. Ahora `engine_requirements.txt` fija NumPy 2.4.6 en Python 3.11 y 2.5.4 en las
versiones más nuevas. Las instalaciones existentes aparecen como «Necesita actualizarse»: basta con pulsar
**Actualizar motor**.
