"""Parsing dos nomes de sessao do KAIST: metadados e rotulo de severidade.

    menor nivel de cada familia   -> WARNING
    niveis intermediario e maior  -> FAILURE
    condicao normal               -> HEALTHY
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# classes de saida do modelo
HEALTHY = "HEALTHY"
WARNING = "WARNING"
FAILURE = "FAILURE"

# familias de falha 
NORMAL = "normal"
BEARING = "bearing"
MISALIGNMENT = "misalignment"
UNBALANCE = "unbalance"

# Ordem de severidade por familia.
# O nivel 1 vira WARNING; os demais viram FAILURE.
SEVERITY_ORDER = {
    BEARING: ["03", "10", "30"],                       # 0.3 / 1.0 / 3.0 mm
    MISALIGNMENT: ["01", "03", "05"],                   # 3 niveis
    UNBALANCE: ["0583", "1169", "1751", "2239", "3318"],  # mg de desbalanceamento
}

# Valor fisico da severidade.
SEVERITY_PHYSICAL = {
    (BEARING, "03"): (0.3, "mm"),
    (BEARING, "10"): (1.0, "mm"),
    (BEARING, "30"): (3.0, "mm"),
    (MISALIGNMENT, "01"): (1.0, "nivel"),
    (MISALIGNMENT, "03"): (2.0, "nivel"),
    (MISALIGNMENT, "05"): (3.0, "nivel"),
    (UNBALANCE, "0583"): (583.0, "mg"),
    (UNBALANCE, "1169"): (1169.0, "mg"),
    (UNBALANCE, "1751"): (1751.0, "mg"),
    (UNBALANCE, "2239"): (2239.0, "mg"),
    (UNBALANCE, "3318"): (3318.0, "mg"),
}


@dataclass(frozen=True)
class SessionMeta:
    """Metadados de uma sessao de gravacao (= um grupo no split treino/teste)."""

    session_id: str        # nome canonico
    load_nm: int           # 0, 2 ou 4 Nm
    fault_family: str      # normal bearing misalignment  unbalance
    fault_location: str    # none  inner_race  outer_race  shaft rotor
    severity_code: str     # codigo cru do nome do arquivo 
    severity_level: int    # 0 = normal, 1..N crescente dentro da familia
    severity_value: float  # valor fisico (mm, nivel ou mg)
    severity_unit: str
    label: str             # HEALTHY WARNING  FAILURE

    @property
    def specimen_id(self) -> str:
        """Identificador da UNIDADE EXPERIMENTAL FISICA.

        O protocolo do KAIST montou cada defeito uma unica vez e o mediu sob as
        tres cargas em sequencia (6 a 43 min de intervalo

        Sao 15 especimes: 1 normal + 14 de falha.
        """
        if self.fault_family == NORMAL:
            return "normal"
        return f"{self.fault_family}/{self.fault_location}/{self.severity_code}"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["specimen_id"] = self.specimen_id
        return d


# Tag canonica usada para montar o session_id, independente do nome do arquivo.
_CANONICAL_TAG = {
    (NORMAL, "none"): "Normal",
    (BEARING, "inner_race"): "BPFI",
    (BEARING, "outer_race"): "BPFO",
    (MISALIGNMENT, "shaft"): "Misalign",
    (UNBALANCE, "rotor"): "Unbalance",
}


def build_session_id(load_nm: int, family: str, location: str, sev_code: str) -> str:
    """session_id canonico e deterministico, identico para o .mat e o .tdms."""
    tag = _CANONICAL_TAG[(family, location)]
    if family == NORMAL:
        return f"{load_nm}Nm_{tag}"
    if family == UNBALANCE:
        return f"{load_nm}Nm_{tag}_{sev_code}mg"
    return f"{load_nm}Nm_{tag}_{sev_code}"


# "Unbalalnce" e um typo presente nos .mat de 2Nm do dataset original.
_TYPO_FIXES = {"unbalalnce": "unbalance"}

_PATTERNS = [
    (re.compile(r"^(?P<load>\d+)nm_normal$"), NORMAL, "none", ""),
    (re.compile(r"^(?P<load>\d+)nm_bpfi_(?P<sev>\d+)$"), BEARING, "inner_race", ""),
    (re.compile(r"^(?P<load>\d+)nm_bpfo_(?P<sev>\d+)$"), BEARING, "outer_race", ""),
    (re.compile(r"^(?P<load>\d+)nm_misalign_(?P<sev>\d+)$"), MISALIGNMENT, "shaft", ""),
    (re.compile(r"^(?P<load>\d+)nm_unbalance_(?P<sev>\d+)mg$"), UNBALANCE, "rotor", "mg"),
]


def canonical_name(raw_name: str) -> str:
    """Normaliza o nome do arquivo (corrige typo) preservando o formato original."""
    name = raw_name
    for wrong, right in _TYPO_FIXES.items():
        name = re.sub(wrong, right, name, flags=re.IGNORECASE)
    return name


def parse_session(raw_name: str) -> SessionMeta:
    """Converte o nome de arquivo (sem extensao) em SessionMeta."""
    canon = canonical_name(raw_name)
    key = canon.lower()

    for pattern, family, location, suffix in _PATTERNS:
        m = pattern.match(key)
        if not m:
            continue

        load_nm = int(m.group("load"))
        sev_code = m.groupdict().get("sev", "") or ""

        if family == NORMAL:
            level, value, unit, label = 0, 0.0, "none", HEALTHY
        else:
            order = SEVERITY_ORDER[family]
            if sev_code not in order:
                raise ValueError(
                    f"severidade '{sev_code}' desconhecida para familia '{family}' "
                    f"(sessao '{raw_name}')"
                )
            level = order.index(sev_code) + 1
            value, unit = SEVERITY_PHYSICAL[(family, sev_code)]
            # DECISAO DE ROTULAGEM: menor nivel da familia -> WARNING, demais -> FAILURE
            label = WARNING if level == 1 else FAILURE

        return SessionMeta(
            session_id=build_session_id(load_nm, family, location, sev_code),
            load_nm=load_nm,
            fault_family=family,
            fault_location=location,
            severity_code=sev_code,
            severity_level=level,
            severity_value=value,
            severity_unit=unit,
            label=label,
        )

    raise ValueError(f"nome de sessao nao reconhecido: '{raw_name}'")
