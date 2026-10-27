"""AI Mocap motion-capture engine.

Runs in an isolated Python environment (never inside Blender's interpreter).
Reads a video, estimates human pose per frame, reconstructs a temporally
coherent motion and writes it using the versioned data contract
(``result.json`` + ``motion.npz``) consumed by the Blender add-on.
"""

ENGINE_VERSION = "0.3.0"
CONTRACT_VERSION = 1
