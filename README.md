# Blender AI Motion Capture

Addon para Blender que genera animación 3D editable (Actions con keyframes) a partir de un vídeo de referencia y la
aplica a un personaje riggeado (Mixamo y rigs humanoides). La IA (MediaPipe) se ejecuta en local, en un entorno
aislado: no toca el Python de Blender ni envía tus vídeos a ningún servicio.

Estado: **Fase 3 completada**: extensión instalable con interfaz completa.

- [docs/INSTALACION.md](docs/INSTALACION.md): instalar el addon y el motor de captura.
- [docs/USO.md](docs/USO.md): guía de los paneles, consejos de grabación y limitaciones.
- [docs/FASE1_DISENO.md](docs/FASE1_DISENO.md): investigación, arquitectura y elección de MediaPipe.
- [docs/FASE2_PROTOTIPO.md](docs/FASE2_PROTOTIPO.md): prototipo de extremo a extremo y métricas de bucle cerrado.
- [docs/FASE3_ADDON.md](docs/FASE3_ADDON.md): addon instalable, pruebas y primera prueba con una persona real.

## En dos minutos

1. `python tools/build_zip.py` → `dist/ai_mocap-0.3.0.zip`.
2. Blender → *Editar → Preferencias → Complementos → ⌄ → Instalar desde disco* → el ZIP.
3. *Sistema → Red → Permitir acceso en línea*; en las preferencias del addon, **Instalar motor**.
4. Visor 3D → **N** → pestaña **AI Mocap**: personaje, vídeo y **Generar animación**.

## Estructura

```
addon/ai_mocap/   extensión de Blender (interfaz, tareas, mapeo, retargeting, escritura de Actions)
engine/           motor de captura (MediaPipe); va dentro del ZIP como engine_src/
tests/            unitarias (pytest), integración del addon (Blender o bpy) y bucle cerrado
tools/            build_zip.py, prototipos de la Fase 2 (run_on_video.py, apply_to_fbx.py)
docs/             documentación en español
```

## Pruebas

```
pytest tests/unit                                   # sin Blender
python tests/blender/test_addon.py                  # con pip install bpy==5.1.2
blender -b --factory-startup --python tests/blender/test_addon.py -- --engine --video clip.mp4
```

Los modelos de MediaPipe, los vídeos y los resultados de las pruebas (`dev/`) y los ZIP generados (`dist/`) no se
versionan.
