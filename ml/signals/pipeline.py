"""Extracao de features por perfil de instrumentacao, identica no treino e em campo.

    perfil          entrada                        features   tipo   severidade
    kaist_full      4 acelerometros + corrente          97    88,7%     63,1%
    field_single    1 canal de vibracao                 25    85,4%     56,1%
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import MS2_TO_G, ROTATION_HZ  # noqa: E402
from kaist.features import current_features, spectral, time_domain  # noqa: E402
from kaist.severity import normative_indicators  # noqa: E402
from signals.readers import RawSignal  # noqa: E402

PROFILE_FULL = "kaist_full"
PROFILE_SINGLE = "field_single"


@dataclass(frozen=True)
class ProfileSpec:
    """Requisitos de entrada de um perfil."""

    name: str
    min_vibration_channels: int
    requires_current: bool
    description: str


PROFILES: dict[str, ProfileSpec] = {
    PROFILE_FULL: ProfileSpec(
        PROFILE_FULL, 4, True,
        "4 acelerometros e uma fase de corrente (bancada instrumentada)"),
    PROFILE_SINGLE: ProfileSpec(
        PROFILE_SINGLE, 1, False,
        "um canal de vibracao (instrumentacao de campo)"),
}


def select_profile(n_vibration_channels: int, has_current: bool) -> str:
    """Escolhe o perfil mais completo compativel com o que foi enviado.
    """
    if n_vibration_channels >= 4 and has_current:
        return PROFILE_FULL
    if n_vibration_channels >= 1:
        return PROFILE_SINGLE
    raise ValueError("nenhum canal de vibracao disponivel")


def _window_count(n_samples: int, fs: float, window_seconds: float) -> int:
    return int(n_samples / int(fs * window_seconds))


def single_channel_features(block_ms2: np.ndarray, fs: float,
                            rot_hz: float = ROTATION_HZ) -> dict[str, float]:
    """Features do perfil `field_single`, a partir de UM canal.

    `block_ms2` tem shape (n,) ou (n, 1), em m/s^2. `rot_hz` posiciona as
    bandas de 1x, 2x e 3x a rotacao.
    """
    coluna = block_ms2.reshape(-1, 1)
    sinal_g = coluna[:, 0] * MS2_TO_G

    out: dict[str, float] = {}
    for k, v in time_domain(sinal_g).items():
        out[f"vib_{k}"] = v

    n = len(sinal_g)
    hann = np.hanning(n)
    amp = np.abs(np.fft.rfft(sinal_g * hann)) * (2.0 / hann.sum())
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    for k, v in spectral(amp, freqs, rot_hz).items():
        out[f"vib_{k}"] = v

    # indicadores normativos calculados do proprio canal
    out.update(normative_indicators(coluna, fs, rot_hz))
    return out


def full_features(block_ms2: np.ndarray, fs_vib: float,
                  current_block: np.ndarray | None, fs_cur: float | None,
                  channel_names: list[str] | None = None,
                  rot_hz: float = ROTATION_HZ) -> dict[str, float]:
    """Features do perfil `kaist_full`: 4 acelerometros + uma fase de corrente."""
    from kaist.features import vibration_features

    out = vibration_features(block_ms2, fs_vib, rot_hz)
    if current_block is not None and fs_cur:
        out.update(current_features(current_block, fs_cur))
    return out


def extract_windows(signal: RawSignal, profile: str, window_seconds: float = 1.0,
                    channel: int = 0, current: RawSignal | None = None,
                    load_nm: float | None = None,
                    rot_hz: float = ROTATION_HZ) -> list[dict[str, float]]:
    """Extrai as features de todas as janelas de um sinal.
    Retorna uma lista de dicionarios, um por janela.
    `rot_hz` e a rotacao do eixo medido. 
    """
    if profile not in PROFILES:
        raise ValueError(f"perfil desconhecido: {profile}")

    fs = signal.sample_rate
    n = int(fs * window_seconds)
    if signal.n_samples < n:
        raise ValueError(
            f"sinal curto demais: {signal.duration_s:.2f}s, "
            f"minimo {window_seconds}s para uma janela")

    janelas: list[dict[str, float]] = []
    total = _window_count(signal.n_samples, fs, window_seconds)

    for w in range(total):
        fatia = slice(w * n, (w + 1) * n)
        if profile == PROFILE_SINGLE:
            linha = single_channel_features(signal.samples[fatia, channel], fs, rot_hz)
        else:
            bloco_cur, fs_cur = None, None
            if current is not None:
                nc = int(current.sample_rate * window_seconds)
                bloco_cur = current.samples[w * nc:(w + 1) * nc, 0]
                fs_cur = current.sample_rate
            linha = full_features(signal.samples[fatia, :4], fs, bloco_cur, fs_cur,
                                  rot_hz=rot_hz)

        if load_nm is not None:
            linha["load_nm"] = float(load_nm)
        janelas.append(linha)

    return janelas


def aggregate_windows(janelas: list[dict[str, float]]) -> dict[str, float]:
    """Resume as janelas de uma medicao numa unica linha de features.
    """
    if not janelas:
        raise ValueError("nenhuma janela extraida")
    chaves = janelas[0].keys()
    return {k: float(np.median([j[k] for j in janelas])) for k in chaves}
