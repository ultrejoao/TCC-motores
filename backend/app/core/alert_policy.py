"""Politica de alertas: oito regras nomeadas, avaliadas em ordem.

    prioridade = severidade x criticidade do motor x agravamento
                 criticidade A=1,5  B=1,0  C=0,7      tendencia = 0,25
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Abaixo deste valor, a predicao do modelo e tratada como pouco confiavel.
CONFIDENCE_THRESHOLD = 0.60

# Variacao sobre a referencia do motor que, sozinha, justifica alerta.
BASELINE_JUMP_PCT = 200.0

# Multiplicadores de criticidade do motor para a producao.
CRITICALITY_WEIGHT = {"A": 1.5, "B": 1.0, "C": 0.7}

# Peso do agravamento entre medicoes consecutivas.
TREND_WEIGHT = 0.25
TREND_CAP = 30.0


class AlertRule(StrEnum):
    """Regra que originou o alerta. Gravada junto com ele."""

    FALHA_CONFIRMADA = "FALHA_CONFIRMADA"
    FALHA_INCERTA = "FALHA_INCERTA"
    NORMA_CRITICA = "NORMA_CRITICA"
    DIVERGENCIA_EM_SAUDAVEL = "DIVERGENCIA_EM_SAUDAVEL"
    SALTO_SOBRE_BASELINE = "SALTO_SOBRE_BASELINE"
    NORMA_ATENCAO = "NORMA_ATENCAO"
    DEGRADACAO = "DEGRADACAO"
    DEGRADACAO_INCERTA = "DEGRADACAO_INCERTA"


#: Severidade e prioridade-base de cada regra.
RULE_TABLE: dict[AlertRule, tuple[str, float, str]] = {
    AlertRule.FALHA_CONFIRMADA: (
        "FAILURE", 100.0,
        "Falha provavel, com evidencias concordantes e alta confianca."),
    AlertRule.NORMA_CRITICA: (
        "FAILURE", 95.0,
        "Vibracao em zona D da ISO 10816: nivel inaceitavel, independente do modelo."),
    AlertRule.FALHA_INCERTA: (
        "FAILURE", 90.0,
        "Falha provavel, porem com evidencias divergentes ou baixa confianca."),
    AlertRule.DIVERGENCIA_EM_SAUDAVEL: (
        "WARNING", 75.0,
        "O modelo classificou como saudavel, mas a assinatura de vibracao "
        "aponta falha. Divergencia nao pode ser ignorada."),
    AlertRule.SALTO_SOBRE_BASELINE: (
        "WARNING", 70.0,
        "Aumento expressivo em relacao a condicao normal conhecida deste motor."),
    AlertRule.NORMA_ATENCAO: (
        "WARNING", 65.0,
        "Vibracao em zona C da ISO 10816: nivel insatisfatorio."),
    AlertRule.DEGRADACAO: (
        "WARNING", 60.0,
        "Degradacao incipiente, com evidencias concordantes."),
    AlertRule.DEGRADACAO_INCERTA: (
        "WARNING", 55.0,
        "Degradacao incipiente, com evidencias divergentes."),
}


@dataclass
class AlertDecision:
    """Resultado da politica para uma medicao."""

    should_alert: bool
    rule: AlertRule | None = None
    severity: str | None = None
    priority_score: float = 0.0
    message: str = ""
    reasons: list[str] = field(default_factory=list)
    trend_pct: float | None = None

    def as_dict(self) -> dict:
        return {
            "rule": str(self.rule) if self.rule else None,
            "severity": self.severity,
            "priority_score": round(self.priority_score, 1),
            "reasons": self.reasons,
            "trend_pct": self.trend_pct,
        }


def _baseline_jump(baseline_comparison: dict | None) -> float | None:
    """Maior aumento percentual entre os indicadores, se houver referencia."""
    if not baseline_comparison:
        return None
    variacoes = [v for k, v in baseline_comparison.items()
                 if k.endswith("_change_pct")]
    return max(variacoes) if variacoes else None


def _trend(indicators: dict[str, float],
           previous: dict[str, float] | None) -> float | None:
    """Agravamento percentual da vibracao global desde a medicao anterior."""
    if not previous:
        return None
    atual = indicators.get("iso_v_rms_mms")
    anterior = previous.get("iso_v_rms_mms")
    if not atual or not anterior:
        return None
    return (atual / anterior - 1.0) * 100.0


def evaluate(*, severity: str, fault_type: str, confidence: float,
             evidence_agreement: bool, physical_type: str | None,
             iso_zone: str | None, indicators: dict[str, float],
             baseline_comparison: dict | None = None,
             previous_indicators: dict[str, float] | None = None,
             criticality: str = "B", motor_tag: str = "",
             is_baseline: bool = False) -> AlertDecision:
    """Aplica a politica. A primeira regra que casa define o alerta.

    A ordem das regras nao e arbitraria: casos de FAILURE e de nivel normativo
    inaceitavel vem primeiro, porque devem prevalecer sobre qualquer nuance de
    confianca ou concordancia.
    """
    confiavel = confidence >= CONFIDENCE_THRESHOLD
    salto = _baseline_jump(baseline_comparison)
    tendencia = _trend(indicators, previous_indicators)
    razoes: list[str] = []

    regra: AlertRule | None = None

    if severity == "FAILURE" and evidence_agreement and confiavel:
        regra = AlertRule.FALHA_CONFIRMADA
    elif iso_zone == "D":
        regra = AlertRule.NORMA_CRITICA
    elif severity == "FAILURE":
        regra = AlertRule.FALHA_INCERTA
        razoes.append("divergencia entre modelo e evidencia fisica"
                      if not evidence_agreement
                      else f"confianca do modelo abaixo de {CONFIDENCE_THRESHOLD:.0%}")
    # Na medicao de referencia a condicao normal e declarada pelo tecnico; a
    # divergencia do modelo contra essa declaracao nao abre alerta. As regras
    # de severidade e de norma continuam valendo para ela.
    elif (severity == "HEALTHY" and not evidence_agreement and not is_baseline
          and physical_type not in (None, "normal")):
        regra = AlertRule.DIVERGENCIA_EM_SAUDAVEL
        razoes.append(
            f"modelo indicou condicao saudavel com {confidence:.0%} de confianca, "
            f"mas a assinatura de vibracao e compativel com '{physical_type}'")
    elif salto is not None and salto >= BASELINE_JUMP_PCT:
        regra = AlertRule.SALTO_SOBRE_BASELINE
        razoes.append(f"aumento de {salto:.0f}% sobre a referencia do motor")
    elif iso_zone == "C":
        regra = AlertRule.NORMA_ATENCAO
    elif severity == "WARNING":
        regra = (AlertRule.DEGRADACAO if evidence_agreement
                 else AlertRule.DEGRADACAO_INCERTA)
        if not evidence_agreement:
            razoes.append("divergencia entre modelo e evidencia fisica")

    if regra is None:
        return AlertDecision(should_alert=False, trend_pct=tendencia)

    sev_alerta, base, explicacao = RULE_TABLE[regra]

    # --- score de prioridade -------------------------------------------------
    peso = CRITICALITY_WEIGHT.get(criticality, 1.0)
    score = base * peso
    if criticality == "A":
        razoes.append("motor critico para a producao (classe A)")

    if tendencia is not None and tendencia > 0:
        bonus = min(tendencia * TREND_WEIGHT, TREND_CAP)
        score += bonus
        if tendencia >= 20:
            razoes.append(f"vibracao {tendencia:.0f}% maior que a medicao anterior")

    if salto is not None and salto > 0 and regra != AlertRule.SALTO_SOBRE_BASELINE:
        razoes.append(f"{salto:.0f}% acima da referencia do motor")

    score = max(0.0, min(score, 200.0))

    prefixo = f"{motor_tag}: " if motor_tag else ""
    mensagem = f"{prefixo}{explicacao}"
    if fault_type and fault_type != "normal":
        mensagem += f" Padrao consistente com {fault_type}."

    return AlertDecision(
        should_alert=True, rule=regra, severity=sev_alerta,
        priority_score=score, message=mensagem, reasons=razoes,
        trend_pct=tendencia)
