# Uso de AI Mocap

Abre la barra lateral del Visor 3D (tecla **N**) y elige la pestaña **AI Mocap**. Los paneles siguen el orden del
trabajo: A → F.

## Flujo rápido

1. **A · Personaje:** selecciona tu personaje (el armature o su malla) y pulsa el cuentagotas. El addon detecta los
   huesos; con un personaje de Mixamo verás «Mixamo · 28/28 huesos mapeados».
2. **B · Vídeo:** elige el vídeo y pulsa **Analizar vídeo** para ver resolución, FPS y duración.
3. **C · Procesamiento:** pulsa **Generar animación**. La IA trabaja en segundo plano con una barra de progreso;
   puedes seguir usando Blender o pulsar **Cancelar**.
4. Al terminar, el personaje tiene una **Action nueva**. Pulsa *Reproducir* en **F · Controles**.

Para probar ajustes rápido, usa **Vista previa (3 s)**, que procesa solo los primeros segundos.

## Paneles

### A · Personaje
- **Personaje:** el armature que recibirá la animación. Si lo dejas vacío, se usa el del objeto seleccionado.
- **Detectar huesos:** reconoce Mixamo (con cualquier prefijo `mixamorig:`, `mixamorig1:`…) y nombres habituales de
  otros rigs (`upper_arm.L`, `Arm_L`, `LeftUpLeg`, `thigh_l`…).
- **Mapeo de huesos** (subpanel): revisa o corrige qué hueso corresponde a cada parte del cuerpo. Los marcados con
  `*` son obligatorios y aparecen en rojo si faltan. El botón de flecha asigna el hueso activo (selecciónalo en modo
  Pose). **Guardar** y **Cargar preset** reutilizan un mapeo en otros personajes del mismo tipo. El mapeo se guarda en
  el `.blend`, dentro del personaje.

### B · Vídeo
- **Recortar:** procesa solo un tramo (inicio y fin en segundos).
- **Vídeo en espejo (selfie):** actívalo si grabaste con la cámara frontal en modo espejo, para que izquierda y
  derecha sean las reales.
- **Avanzado → Rotación:** solo si el vídeo se ve tumbado. La rotación que guardan los móviles se aplica sola.

### C · Procesamiento
- **Modelo:** *Lite* (rápido), *Full* (recomendado) o *Heavy* (más lento; mejor con personas lejanas o con poca luz).
- **FPS:** *De la escena* (recomendado: un keyframe por fotograma), *Del vídeo* o *Personalizado*.
- **Suavizado:** más alto quita temblor; demasiado alto suaviza los golpes o movimientos rápidos.
- **Avanzado:** confianza mínima, **Interpolar huecos de hasta** (los huecos breves se interpolan; si una parte del
  cuerpo queda tapada más tiempo, se usa la estimación de la IA en vez de congelar la pose de otro momento), campo de
  visión de la cámara, orientación inicial, «Persona de pie» (desactívalo
  para volteretas o el pino) y **Reutilizar análisis**.
- **Regenerar sin IA:** crea otra Action desde el último análisis con los ajustes actuales de retargeting y salida.
  Tarda menos de un segundo.

**Caché:** cada vídeo se analiza con IA una sola vez por combinación de ajustes de procesamiento. Si vuelves a
generar con los mismos ajustes, el resultado sale de la caché al instante. Cambiar el vídeo, el recorte, el modelo, el
FPS o el suavizado obliga a un análisis nuevo. Cambiar el retargeting o la salida no.

### D · Retargeting
- **Desplazamiento:** *Completo* (el personaje se mueve por la escena), *Solo vertical* (en el sitio, pero conserva
  saltos y agachados) o *Ninguno* (solo rotaciones).
- **Escala del recorrido**, **Giro adicional** (orientar toda la animación) y **Seguimiento de manos**.
- **Avanzado:** reparto del giro entre cuello y cabeza, y corrección de la inclinación neutra de la cabeza.

### E · Salida
- **Nombre:** por defecto `Mocap_<nombre del vídeo>`. Nunca se sobrescribe una Action existente: si el nombre está
  usado, se añade `.001`, `.002`…
- **Empieza en:** inicio de escena, fotograma actual o uno concreto.
- **Keyframe cada:** 1 = un keyframe por fotograma (máxima fidelidad). Con 2–4 las curvas son más ligeras y fáciles
  de retocar; la interpolación pasa a Bézier.
- **Ajustar rango de la escena** y **Enviar al NLA** (para mezclar o encadenar animaciones).
- Debajo verás el informe de la última generación: fotogramas, huesos, porcentaje del vídeo con la persona detectada
  y tiempos.

### F · Controles
Reproducir, pausa e ir al inicio o al final; ver la pose de reposo; enviar la Action actual al NLA; cambiar entre
animaciones generadas o eliminarlas; y **Restaurar animación original** para volver a la Action que tenía el personaje
antes de usar el addon (esa Action nunca se borra).

## Editar la animación

El resultado es una Action normal, con un F-Curve por canal y huesos agrupados. Se puede editar en el **Dope Sheet**,
el **Graph Editor** o el **NLA**, usar capas de animación encima, y exportar a FBX o glTF como cualquier otra
animación.

## Consejos para grabar el vídeo

- El cuerpo entero dentro del encuadre todo el tiempo, de la cabeza a los pies.
- Cámara fija (trípode o apoyada), una sola persona en primer plano y buena luz.
- Ropa que contraste con el fondo; evita prendas muy anchas.
- Empieza mirando a la cámara. Grabar en ángulo de ¾ ayuda a captar mejor la profundidad.

## Limitaciones actuales

- **Profundidad:** con una sola cámara, los movimientos hacia la cámara o desde ella se estiman peor que los laterales.
- **Trayectoria:** el desplazamiento por la escena es aproximado. Si la persona empieza lejos, el personaje puede
  flotar o hundirse unos centímetros. Usa *Solo vertical* si solo te interesa el movimiento del cuerpo.
- **Pies:** pueden deslizarse un poco; aún no se fijan al suelo.
- **Manos:** orientación aproximada y **sin dedos**.
- **Brazos por encima de la cabeza:** el giro del brazo puede fallar en algunos fotogramas.
- Se sigue a **una sola persona**.
- **Personajes no humanos** (dibujos, criaturas con proporciones extrañas): la IA está entrenada con personas reales.
  Suele funcionar, pero con más errores, sobre todo de perfil. Un vídeo de una persona real haciendo el mismo
  movimiento da mejor resultado.
