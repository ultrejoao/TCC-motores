"""Leitura dos sinais brutos do KAIST.

Duas modalidades, dois formatos e duas taxas de amostragem:

    vibracao          .mat (MATLAB v5, LMS Test.Lab)  4 canais  25600.00 Hz  [m/s^2]
    corrente+temp     .tdms (NI FlexLogger)           5 canais  25608.19 Hz  [A, degC]

A acustica existe para apenas 5 das 45 sessoes e por isso nao e usada como
feature do modelo v1 (ver docs/01-inventario-dataset.md).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from nptdms import TdmsFile
from scipy.io import loadmat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (  # noqa: E402
    FS_VIBRATION,
    TDMS_CHANNEL_MAP,
    TDMS_DIR,
    TDMS_GROUP,
    VIBRATION_CHANNELS,
    VIBRATION_DIR,
)
from kaist.sessions import SessionMeta, parse_session  # noqa: E402


@dataclass(frozen=True)
class SessionFiles:
    """Localiza os arquivos das duas modalidades de uma mesma sessao."""

    meta: SessionMeta
    vibration_path: Path | None
    tdms_path: Path | None

    @property
    def complete(self) -> bool:
        return self.vibration_path is not None and self.tdms_path is not None


def _is_real_data_file(path: Path) -> bool:
    
    return not path.name.startswith(("~$", ".") ) and path.stat().st_size > 1024


def discover_sessions() -> dict[str, SessionFiles]:
    """Varre os diretorios e pareia .mat e .tdms pelo session_id canonico."""
    vib: dict[str, Path] = {}
    for p in sorted(VIBRATION_DIR.glob("*.mat")):
        if _is_real_data_file(p):
            vib[parse_session(p.stem).session_id] = p

    tdms: dict[str, Path] = {}
    for p in sorted(TDMS_DIR.glob("*.tdms")):
        if _is_real_data_file(p):
            tdms[parse_session(p.stem).session_id] = p

    out: dict[str, SessionFiles] = {}
    for sid in sorted(set(vib) | set(tdms)):
        out[sid] = SessionFiles(
            meta=parse_session(sid),
            vibration_path=vib.get(sid),
            tdms_path=tdms.get(sid),
        )
    return out


def load_vibration(path: Path) -> tuple[np.ndarray, float]:
    """Retorna (sinal (n, 4) em m/s^2, fs em Hz).
    """
    mat = loadmat(path, struct_as_record=False, squeeze_me=True)
    signal = mat["Signal"]
    values = np.asarray(signal.y_values.values, dtype=np.float64)
    increment = float(signal.x_values.increment)
    fs = 1.0 / increment

    if values.ndim != 2 or values.shape[1] != len(VIBRATION_CHANNELS):
        raise ValueError(f"{path.name}: esperado (n, 4), obtido {values.shape}")
    if not np.isclose(fs, FS_VIBRATION, rtol=1e-6):
        raise ValueError(f"{path.name}: fs inesperado {fs:.3f} Hz")

    return values, fs


def load_current_temp(path: Path) -> tuple[dict[str, np.ndarray], float]:
    """Retorna ({'temp1','temp2','current_r','current_s','current_t'}, fs)."""
    channels: dict[str, np.ndarray] = {}
    fs: float | None = None

    with TdmsFile.open(path) as tf:
        group = tf[TDMS_GROUP]
        for ch in group.channels():
            name = TDMS_CHANNEL_MAP.get(ch.name)
            if name is None:
                continue
            channels[name] = np.asarray(ch[:], dtype=np.float64)
            if fs is None:
                fs = 1.0 / float(ch.properties["wf_increment"])

    missing = set(TDMS_CHANNEL_MAP.values()) - set(channels)
    if missing:
        raise ValueError(f"{path.name}: canais ausentes {sorted(missing)}")

    return channels, float(fs)
