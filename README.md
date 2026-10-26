# Blender AI Motion Capture

Addon para Blender que genera animación 3D editable (Actions con keyframes) a partir de un vídeo de referencia y la aplica a un personaje riggeado (Mixamo).

Estado: **Fase 2 completada** (prueba de viabilidad). Ver:

- [docs/FASE1_DISENO.md](docs/FASE1_DISENO.md): investigación, arquitectura y elección de MediaPipe.
- [docs/FASE2_PROTOTIPO.md](docs/FASE2_PROTOTIPO.md): prototipo de extremo a extremo, métricas de la prueba de bucle cerrado y limitaciones.

## Estructura

```
addon/ai_mocap/   código del addon (mapeo de huesos, retargeting, escritura de Actions)
engine/           motor de captura (MediaPipe, entorno Python aislado)
tests/            pruebas unitarias, de integración en Blender y de bucle cerrado
tools/            utilidades de desarrollo (run_on_video.py)
docs/             documentación en español
```

Los modelos de MediaPipe y los resultados de las pruebas (`dev/`) no se versionan; se regeneran con los scripts.
