"""Reader for the engine output contract (result.json + motion.npz)."""

import json
import os
from dataclasses import dataclass

import numpy as np

SUPPORTED_CONTRACT_VERSIONS = (1,)
REQUIRED_ARRAYS = ("world", "root", "confidence", "valid")


class ContractError(Exception):
    pass


@dataclass
class Motion:
    meta: dict
    world: np.ndarray       # (F, J, 3) metres, pelvis-relative, contract space
    root: np.ndarray        # (F, 3)
    confidence: np.ndarray  # (F, J)
    valid: np.ndarray       # (F,)
    fps: float

    @property
    def frame_count(self):
        return self.world.shape[0]


def load_motion(out_dir):
    meta_path = os.path.join(out_dir, "result.json")
    npz_path = os.path.join(out_dir, "motion.npz")
    if not (os.path.isfile(meta_path) and os.path.isfile(npz_path)):
        raise ContractError(f"Resultado del motor incompleto en {out_dir}")
    with open(meta_path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    version = meta.get("contract_version")
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractError(f"Versión de contrato no soportada: {version}")
    with np.load(npz_path, allow_pickle=False) as data:
        missing = [k for k in REQUIRED_ARRAYS if k not in data.files]
        if missing:
            raise ContractError(f"Faltan datos en motion.npz: {missing}")
        arrays = {k: np.array(data[k]) for k in REQUIRED_ARRAYS}
    F = arrays["world"].shape[0]
    if arrays["world"].shape[1:] != (len(meta["joint_names"]), 3) or arrays["root"].shape != (F, 3):
        raise ContractError("Dimensiones inconsistentes en motion.npz")
    return Motion(meta=meta, world=arrays["world"].astype(np.float64),
                  root=arrays["root"].astype(np.float64),
                  confidence=arrays["confidence"], valid=arrays["valid"].astype(bool),
                  fps=float(meta["fps"]))
