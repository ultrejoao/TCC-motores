"""Extracao de caracteristicas por janela.

Tres exclusoes que nao se inferem do codigo:

    temperatura   variacao entre sessoes 7x maior que dentro de uma sessao;
                  e impressao digital da gravacao, entraria como vazamento
    corrente      uma fase so: as 9 sessoes BPFO tem S e T vazias no original
    acustica      o pacote cobre 5 das 45 sessoes

Features espectrais sao obrigatorias: o desbalanceamento e indistinguivel do
normal no RMS (0,102 -> 0,105 g), mas separa em 1x (0,00069 -> 0,00241).

    vib_<canal>_<feature>   entra no modelo
    cur_<feature>           entra no modelo
    load_nm                 entra no modelo
    meta_<...>              NAO entra no modelo
"""

from __future__ import annotations

import numpy as np

from config import MS2_TO_G, ROTATION_HZ, VIBRATION_CHANNELS
from kaist.severity import normative_indicators

# Bandas de energia (Hz) para o sinal de vibracao.
ENERGY_BANDS = {
    "band_lo": (10.0, 200.0),         # desbalanceamento, desalinhamento, folgas
    "band_mid": (200.0, 1_000.0),     # harmonicos estruturais
    "band_hi": (1_000.0, 5_000.0),    # impacto de rolamento
    "band_vhi": (5_000.0, 12_000.0),  # ressonancia de alta frequencia
}

HARMONIC_HALF_WIDTH = 1.5  # Hz, meia-largura da banda em torno de cada harmonico
_EPS = 1e-12


def time_domain(x: np.ndarray) -> dict[str, float]:
    """Descritores estatisticos classicos de vibracao no dominio do tempo."""
    centered = x - x.mean()
    std = centered.std()
    rms = np.sqrt(np.mean(x**2))
    abs_x = np.abs(x)
    peak = abs_x.max()
    mean_abs = abs_x.mean()

    return {
        "rms": float(rms),
        "peak": float(peak),
        "p2p": float(x.max() - x.min()),
        "std": float(std),
        "kurtosis": float(np.mean(centered**4) / (std**4 + _EPS)),
        "skewness": float(np.mean(centered**3) / (std**3 + _EPS)),
        "crest_factor": float(peak / (rms + _EPS)),
        "shape_factor": float(rms / (mean_abs + _EPS)),
        "impulse_factor": float(peak / (mean_abs + _EPS)),
        "clearance_factor": float(peak / (np.mean(np.sqrt(abs_x)) ** 2 + _EPS)),
    }


def _band_amplitude(freqs: np.ndarray, amp: np.ndarray, lo: float, hi: float) -> float:
    """Maior amplitude espectral dentro da banda [lo, hi]."""
    sel = (freqs >= lo) & (freqs <= hi)
    return float(amp[sel].max()) if sel.any() else 0.0


def _band_energy(freqs: np.ndarray, amp: np.ndarray, lo: float, hi: float) -> float:
    """Energia RMS na banda [lo, hi]."""
    sel = (freqs >= lo) & (freqs <= hi)
    return float(np.sqrt(np.sum(amp[sel] ** 2))) if sel.any() else 0.0


def spectral(amp: np.ndarray, freqs: np.ndarray, rot_hz: float = ROTATION_HZ) -> dict[str, float]:
    """Features espectrais: harmonicos da rotacao, razoes e energia por banda."""
    h = HARMONIC_HALF_WIDTH
    a1 = _band_amplitude(freqs, amp, rot_hz - h, rot_hz + h)
    a2 = _band_amplitude(freqs, amp, 2 * rot_hz - h, 2 * rot_hz + h)
    a3 = _band_amplitude(freqs, amp, 3 * rot_hz - h, 3 * rot_hz + h)

    out: dict[str, float] = {
        "amp_1x": a1,                                  # desbalanceamento
        "amp_2x": a2,                                  # desalinhamento
        "amp_3x": a3,
        "ratio_2x_1x": float(a2 / (a1 + _EPS)),
        "ratio_3x_1x": float(a3 / (a1 + _EPS)),
    }

    for name, (lo, hi) in ENERGY_BANDS.items():
        out[name] = _band_energy(freqs, amp, lo, hi)

    total = float(np.sqrt(np.sum(amp**2))) + _EPS
    out["ratio_hi_total"] = out["band_hi"] / total
    out["spectral_centroid"] = float(np.sum(freqs * amp) / (np.sum(amp) + _EPS))
    return out


def _spectrum(block: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Espectro de amplitude unilateral com janela de Hann.

    `block` pode ser (n,) ou (n, canais); o eixo 0 e sempre o tempo.
    """
    n = block.shape[0]
    hann = np.hanning(n)
    window = hann[:, None] if block.ndim == 2 else hann
    scale = 2.0 / hann.sum()
    amp = np.abs(np.fft.rfft(block * window, axis=0)) * scale
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    return freqs, amp


def vibration_features(block: np.ndarray, fs: float,
                       rot_hz: float = ROTATION_HZ) -> dict[str, float]:
    """Features dos 4 acelerometros para uma janela. `block` em m/s^2, shape (n, 4).

    `rot_hz` e a rotacao do eixo, que posiciona as bandas de 1x, 2x e 3x. O
    padrao e a rotacao da bancada KAIST, usada no treino; em campo o valor vem
    da rotacao do motor medido — buscar 1x a 50,15 Hz num motor de 1.780 rpm
    mediria ruido, e o erro nao apareceria em lugar nenhum.
    """
    block_g = block * MS2_TO_G          # analise feita em g
    freqs, amp = _spectrum(block_g, fs)

    out: dict[str, float] = {}
    for i, ch in enumerate(VIBRATION_CHANNELS):
        for k, v in time_domain(block_g[:, i]).items():
            out[f"vib_{ch}_{k}"] = v
        for k, v in spectral(amp[:, i], freqs, rot_hz).items():
            out[f"vib_{ch}_{k}"] = v

    # indicadores normativos (ISO 10816/20816): entram como features e tambem
    # sao exibidos ao usuario como camada de validacao fisica
    out.update(normative_indicators(block, fs, rot_hz))
    return out


def current_features(block: np.ndarray, fs: float) -> dict[str, float]:
    """Features de uma fase de corrente (MCSA simplificada)."""
    freqs, amp = _spectrum(block, fs)

    rms = float(np.sqrt(np.mean(block**2)))
    peak = float(np.abs(block).max())

    sel = (freqs >= 20) & (freqs <= 120)
    f_line = float(freqs[sel][np.argmax(amp[sel])])
    a_line = _band_amplitude(freqs, amp, f_line - 1.5, f_line + 1.5)
    a_h3 = _band_amplitude(freqs, amp, 3 * f_line - 2, 3 * f_line + 2)
    a_h5 = _band_amplitude(freqs, amp, 5 * f_line - 2, 5 * f_line + 2)

    # bandas laterais da fundamental: indicio classico de falha mecanica (MCSA)
    side = (_band_energy(freqs, amp, f_line - 15, f_line - 2)
            + _band_energy(freqs, amp, f_line + 2, f_line + 15))

    return {
        "cur_rms": rms,
        "cur_peak": peak,
        "cur_crest_factor": float(peak / (rms + _EPS)),
        "cur_line_freq": f_line,
        "cur_amp_line": a_line,
        "cur_ratio_h3": float(a_h3 / (a_line + _EPS)),
        "cur_ratio_h5": float(a_h5 / (a_line + _EPS)),
        "cur_sideband_ratio": float(side / (a_line + _EPS)),
    }


def temperature_metadata(temp1: np.ndarray, temp2: np.ndarray) -> dict[str, float]:
    """Temperatura NAO entra no modelo"""
    return {
        "meta_temp1_mean": float(temp1.mean()),
        "meta_temp2_mean": float(temp2.mean()),
        "meta_temp_delta": float(temp2.mean() - temp1.mean()),
    }


def model_feature_columns(columns) -> list[str]:
    """Filtra as colunas que efetivamente alimentam o modelo."""
    return [c for c in columns if c.startswith(("vib_", "cur_", "iso_")) or c == "load_nm"]
