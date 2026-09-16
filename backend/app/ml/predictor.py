"""Servico de inferencia.

Carrega o artefato do perfil adequado, extrai as features do sinal recebido,
executa o ensemble nos dois alvos e cruza o resultado com a evidencia fisica.

"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.config import get_settings

settings = get_settings()

# o pipeline de features e compartilhado com o treino: o mesmo codigo, para que
# as features de producao sejam identicas as que o modelo viu treinando
ML_ROOT = settings.model_artifact.parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from kaist.decision import decide  # noqa: E402
from kaist import physical_severity  # noqa: E402
from kaist.severity import compare_to_baseline  # noqa: E402
from signals.pipeline import (  # noqa: E402
    aggregate_windows,
    extract_windows,
    select_profile,
)
from signals.readers import RawSignal  # noqa: E402

INDICATORS = ["iso_v_rms_mms", "iso_v_1x_mms", "iso_v_2x_mms", "iso_a_hf_g"]


class ModelNotAvailable(RuntimeError):
    """Nenhum artefato utilizavel para o perfil pedido."""


@dataclass
class PredictionResult:
    """Saida do diagnostico.

    `ml_severity` e mantida como resultado do experimento preliminar, para
    comparacao.
    """

    profile: str
    model_version: str

    # severidade por criterio fisico — saida primaria
    severity: str
    severity_criterion: str
    severity_explanation: str
    iso_zone: str
    v_rms_mms: float
    ratio_to_baseline: float | None

    # severidade prevista pelo modelo — experimento preliminar.
    ml_severity: str
    ml_severity_probabilities: dict[str, float]

    fault_type: str
    fault_type_probabilities: dict[str, float]

    physical_type: str
    evidence_agreement: bool
    confidence: float
    recommendation: str

    features: dict[str, float]
    indicators: dict[str, float]
    top_factors: list[dict[str, Any]] = field(default_factory=list)
    baseline_comparison: dict[str, float] | None = None
    n_windows: int = 0
    inference_ms: float = 0.0


class Predictor:
    """Carrega e mantem em memoria os artefatos de modelo."""

    def __init__(self) -> None:
        self._bundles: dict[str, dict] = {}

    def load(self, profile: str) -> dict:
        if profile in self._bundles:
            return self._bundles[profile]

        caminho = Path(settings.model_artifact.parent) / f"model_{profile}_v1.joblib"
        if not caminho.exists():
            raise ModelNotAvailable(
                f"artefato do perfil '{profile}' nao encontrado em {caminho}. "
                f"Execute ml/scripts/09_train_profiles.py.")

        self._bundles[profile] = joblib.load(caminho)
        return self._bundles[profile]

    def available_profiles(self) -> list[str]:
        base = Path(settings.model_artifact.parent)
        return sorted(p.stem.replace("model_", "").replace("_v1", "")
                      for p in base.glob("model_*_v1.joblib"))

    def _run_target(self, bundle: dict, target: str,
                    X: np.ndarray) -> tuple[str, dict[str, float]]:
        cfg = bundle["targets"][target]
        proba = (cfg["rf"].predict_proba(X) + cfg["xgb"].predict_proba(X)) / 2.0
        probs = {c: float(p) for c, p in zip(cfg["classes"], proba[0], strict=True)}
        return cfg["classes"][int(proba[0].argmax())], probs

    def _top_factors(self, bundle: dict, target: str, X: np.ndarray,
                     colunas: list[str], k: int = 5) -> list[dict[str, Any]]:
        """Principais fatores da decisao.
        """
        rf = bundle["targets"][target]["rf"]
        importancias = rf.feature_importances_
        ordem = np.argsort(importancias)[::-1][:k]
        total = float(importancias[ordem].sum()) or 1.0
        return [{"feature": colunas[i],
                 "contribution": round(float(importancias[i] / total), 4),
                 "value": round(float(X[0, i]), 6)}
                for i in ordem]

    def predict(self, signal: RawSignal, *, channel: int = 0,
                current: RawSignal | None = None, load_nm: float | None = None,
                baseline: dict[str, float] | None = None,
                machine_class: str = "I",
                rot_hz: float | None = None,
                profile: str | None = None) -> PredictionResult:
        inicio = time.perf_counter()

        escolhido = profile or select_profile(signal.n_channels, current is not None)
        bundle = self.load(escolhido)

        janelas = extract_windows(
            signal, escolhido, window_seconds=bundle.get("window_seconds", 1.0),
            channel=channel, current=current, load_nm=load_nm,
            **({"rot_hz": rot_hz} if rot_hz else {}))
        features = aggregate_windows(janelas)

        colunas = bundle["feature_columns"]
        faltando = [c for c in colunas if c not in features]
        if faltando:
            raise ModelNotAvailable(
                f"o sinal enviado nao produz {len(faltando)} feature(s) exigidas "
                f"pelo perfil '{escolhido}': {faltando[:5]}")

        X = np.array([[features[c] for c in colunas]], dtype=np.float32)

        ml_sev, probs_sev = self._run_target(bundle, "severity", X)
        tipo, probs_tipo = self._run_target(bundle, "fault_type", X)

        indicadores = {k: float(features[k]) for k in INDICATORS if k in features}

        # SEVERIDADE POR CRITERIO FISICO — independente do modelo
        fisica = physical_severity.evaluate(
            indicadores, machine_class=machine_class,
            baseline=baseline, fault_type=tipo)

        # a matriz de decisao cruza o TIPO previsto com a assinatura fisica
        decisao = decide(tipo, probs_tipo[tipo], fisica.severity, probs_tipo[tipo],
                         indicadores, bundle["physical_signature"])

        return PredictionResult(
            profile=escolhido,
            model_version=f"{escolhido}_{bundle['version']}",
            severity=fisica.severity,
            severity_criterion=str(fisica.criterion),
            severity_explanation=fisica.explanation,
            iso_zone=fisica.iso_zone,
            v_rms_mms=fisica.v_rms_mms,
            ratio_to_baseline=fisica.ratio_to_baseline,
            ml_severity=ml_sev, ml_severity_probabilities=probs_sev,
            fault_type=tipo, fault_type_probabilities=probs_tipo,
            physical_type=decisao.physical_type,
            evidence_agreement=decisao.agreement,
            confidence=decisao.confidence,
            recommendation=decisao.recommendation,
            features=features, indicators=indicadores,
            top_factors=self._top_factors(bundle, "fault_type", X, colunas),
            baseline_comparison=compare_to_baseline(indicadores, baseline),
            n_windows=len(janelas),
            inference_ms=round((time.perf_counter() - inicio) * 1000, 2),
        )


_predictor: Predictor | None = None


def get_predictor() -> Predictor:
    global _predictor
    if _predictor is None:
        _predictor = Predictor()
    return _predictor
