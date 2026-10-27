# Instalación de AI Mocap

Requisitos: **Blender 4.4 o superior** (probado en 5.1.2), Windows, Linux o macOS, unos **550 MB** libres y conexión a
internet solo durante la instalación. No hace falta GPU ni cuenta en ningún servicio: todo se procesa en tu equipo.

## 1. Instalar el addon

1. Consigue el archivo `ai_mocap-0.3.0.zip` (o genéralo desde el repositorio con `python tools/build_zip.py`;
   aparece en `dist/`).
2. En Blender: **Editar → Preferencias → Complementos**. Pulsa la flecha ⌄ de la esquina superior derecha y elige
   **Instalar desde disco…**. Selecciona el `.zip`.
   *(También puedes arrastrar el `.zip` sobre la ventana de Blender).*
3. El addon queda activado como **AI Mocap**.

## 2. Permitir el acceso a internet (una sola vez)

Blender bloquea por defecto que las extensiones usen la red. Ve a **Preferencias → Sistema → Red** y activa
**Permitir acceso en línea**. Solo se usa para descargar el motor y los modelos; los vídeos nunca salen de tu equipo.
Después de instalar el motor puedes volver a desactivarlo.

## 3. Instalar el motor de captura

En **Preferencias → Complementos → AI Mocap**, pulsa **Instalar motor**. El addon:

1. crea un entorno de Python aislado a partir del Python de Blender (no toca la instalación de Blender);
2. instala MediaPipe 1.1.1, OpenCV 5.0 y NumPy 2.5.4 (unos 470 MB de descarga);
3. descarga el modelo de pose *Full* (9 MB) y comprueba su huella SHA-256;
4. hace una autoprueba: arranca el motor, carga el modelo y procesa una imagen de prueba.

Verás el progreso en la propia ventana de preferencias y puedes cancelarlo. Blender sigue funcionando mientras tanto.
Al terminar, el estado pasa a **Listo**.

Los modelos *Lite* (más rápido) y *Heavy* (más preciso y lento) se descargan con su botón o automáticamente la primera
vez que los elijas en el panel de procesamiento.

### Dónde se guarda

En la carpeta de usuario de la extensión (en Windows,
`%APPDATA%\Blender Foundation\Blender\<versión>\extensions\.user\user_default\ai_mocap`): el motor (`engine_venv`),
los modelos, la caché de análisis, los presets de mapeo y los registros. El botón de carpeta la abre en el explorador.
Si prefieres otro disco o una ruta más corta, cámbiala en **Carpeta de datos** antes de instalar.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| «Blender no tiene permitido el acceso a internet» | Activa *Permitir acceso en línea* (paso 2). |
| «La carpeta de instalación tiene una ruta demasiado larga para Windows» | Elige una carpeta corta, por ejemplo `C:\AIMocap`, en **Carpeta de datos** y vuelve a instalar. También vale activar las rutas largas de Windows. |
| «pip no pudo instalar las dependencias» | Revisa la conexión, el antivirus (a veces bloquea la descarga) o el espacio en disco, y pulsa **Reinstalar**. El botón **Ver registro** muestra el detalle. |
| «El modelo descargado no coincide con la huella esperada» | La descarga llegó dañada o el archivo cambió en el servidor. Vuelve a intentarlo. |
| Linux: «libEGL.so.1: cannot open shared object file» | MediaPipe necesita las librerías gráficas del sistema: `sudo apt install libegl1 libgles2`. Después pulsa **Verificar**. |
| «Esta versión del addon necesita actualizar el motor» | Tras actualizar el addon, pulsa **Actualizar motor**. |

## Desinstalar

1. En las preferencias del addon pulsa **Eliminar** (borra el motor) y **Vaciar caché**.
2. Desinstala el addon desde la lista de complementos.
Las animaciones que ya generaste son Actions normales de Blender y se quedan en tus `.blend`.
