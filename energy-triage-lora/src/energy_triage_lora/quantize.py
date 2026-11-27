"""Post-training int8 weight quantisation, per output channel and symmetric.

Each row of a weight matrix gets its own scale (max |w| / 127), so one large row does not crush
the precision of the others. Written in NumPy so it can be tested without torch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class QuantizedTensor:
    values: np.ndarray  # int8, same shape as the weight
    scales: np.ndarray  # float32, one per row

    @property
    def nbytes(self) -> int:
        return int(self.values.nbytes + self.scales.nbytes)

    def dequantize(self) -> np.ndarray:
        return (self.values.astype(np.float32) * self.scales[:, None]).reshape(self.values.shape)


def quantize(weight: np.ndarray) -> QuantizedTensor:
    w = np.asarray(weight, dtype=np.float32)
    if w.ndim != 2:
        raise ValueError("per-channel quantisation expects a 2-D weight")
    scales = np.abs(w).max(axis=1) / 127.0
    scales = np.where(scales == 0, 1.0, scales).astype(np.float32)
    values = np.clip(np.rint(w / scales[:, None]), -127, 127).astype(np.int8)
    return QuantizedTensor(values, scales)


def quantize_state(state: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Quantises every 2-D weight and leaves biases and norms in float32.

    Returns the dequantised weights (to load back into the model and measure the accuracy cost)
    and the byte counts before and after.
    """
    out: dict[str, np.ndarray] = {}
    before = after = 0
    for name, tensor in state.items():
        arr = np.asarray(tensor, dtype=np.float32)
        before += arr.nbytes
        if arr.ndim == 2:
            q = quantize(arr)
            out[name] = q.dequantize()
            after += q.nbytes
        else:
            out[name] = arr
            after += arr.nbytes
    return out, {"float32_bytes": before, "int8_bytes": after}
