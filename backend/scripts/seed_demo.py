"""Cria os tres motores de demonstracao a partir das amostras em ml/data/demo_samples.

Uso, com o sistema no ar e o ADMIN ja criado:
    docker compose exec api python scripts/seed_demo.py
    docker compose exec api python scripts/seed_demo.py --recriar
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.deps import get_current_user, require_csrf  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.hierarchy import Area, Line, Plant  # noqa: E402
from app.models.measurement import Measurement  # noqa: E402
from app.models.ml_model import MLModel  # noqa: E402
from app.models.motor import Motor  # noqa: E402
from app.models.user import User  # noqa: E402

AMOSTRAS = Path(__file__).resolve().parents[2] / "ml" / "data" / "demo_samples"
REFERENCIA = "2Nm_Normal"
ROTACAO_RPM = 3009

NOTA = ("Motor de demonstracao. Sinais do dataset KAIST, de um especime reservado: "
        "o modelo nunca viu nenhuma medicao desta montagem no treino.")

# (tag, nome, criticidade, coletas). O MT-101 fica sem a coleta de 2 Nm, que e
# enviada ao vivo na apresentacao.
MOTORES = [
    ("MT-101", "Motor da Bomba de Recalque", "A",
     ["0Nm_BPFO_10", "4Nm_BPFO_10"]),
    ("MT-102", "Motor do Ventilador de Exaustao", "B",
     ["0Nm_Unbalance_2239mg", "2Nm_Unbalance_2239mg", "4Nm_Unbalance_2239mg"]),
    ("MT-103", "Motor do Compressor de Ar", "C",
     ["0Nm_Misalign_03", "2Nm_Misalign_03", "4Nm_Misalign_03"]),
]


def verificar_pre_requisitos(db) -> User | None:
    faltando = [n for n in [REFERENCIA, *(s for *_, c in MOTORES for s in c)]
                if not (AMOSTRAS / f"{n}.csv").exists()]
    if faltando:
        print(f"[erro] amostras ausentes em {AMOSTRAS}: {faltando}")
        return None
    if not db.scalar(select(func.count()).select_from(MLModel)):
        print("[erro] nenhum modelo registrado. Reinicie a API para o registro automatico.")
        return None
    admin = db.scalar(select(User).where(User.role == "ADMIN", User.is_active.is_(True)))
    if admin is None:
        print("[erro] nenhum ADMIN no banco. Rode antes: python scripts/seed_admin.py")
    return admin


def remover_existentes(db, recriar: bool) -> bool:
    tags = [m[0] for m in MOTORES]
    existentes = db.scalars(select(Motor).where(Motor.tag.in_(tags))).all()
    if not existentes:
        return True
    if not recriar:
        print(f"[erro] ja existem: {sorted(m.tag for m in existentes)}")
        print("       use --recriar para apaga-los e criar de novo.")
        return False

    ids = [m.id for m in existentes]
    arquivos = db.scalars(select(Measurement.source_path)
                          .where(Measurement.motor_id.in_(ids))).all()
    db.execute(delete(Motor).where(Motor.id.in_(ids)))
    db.commit()
    for caminho in filter(None, arquivos):
        Path(caminho).unlink(missing_ok=True)
    print(f"removidos: {sorted(m.tag for m in existentes)}")
    return True


def buscar_ou_criar(c, prefixo: str, db, modelo, filtro: dict, rota: str, dados: dict) -> str:
    existente = db.scalar(select(modelo).filter_by(**filtro))
    if existente:
        return str(existente.id)
    r = c.post(prefixo + rota, json=dados)
    r.raise_for_status()
    return r.json()["id"]


def enviar(c, prefixo: str, motor_id: str, nome: str, dias_atras: int,
           referencia: bool, agora: datetime) -> dict:
    contexto = {
        "motor_id": motor_id,
        "collected_at": (agora - timedelta(days=dias_atras)).isoformat(),
        "load_nm": float(nome[0]),
        "rpm": ROTACAO_RPM,
        "sample_rate_hz": 25600,
        "unit": "m/s^2",
        "is_baseline": referencia,
        "notes": "Medicao de referencia: condicao normal do motor." if referencia else None,
    }
    with open(AMOSTRAS / f"{nome}.csv", "rb") as f:
        r = c.post(prefixo + "/measurements",
                   files={"file": (f"{nome}.csv", f, "text/csv")},
                   data={"context": json.dumps(contexto)})
    if r.status_code != 201:
        raise RuntimeError(f"{nome}: {r.status_code} {r.text}")
    return r.json()["prediction"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Cria os motores de demonstracao.")
    parser.add_argument("--recriar", action="store_true",
                        help="apaga MT-101, MT-102 e MT-103 antes de criar")
    args = parser.parse_args()

    prefixo = get_settings().api_v1_prefix
    with SessionLocal() as db:
        admin = verificar_pre_requisitos(db)
        if admin is None or not remover_existentes(db, args.recriar):
            return 1
        # o commit da remocao expira o objeto; recarrega antes de sair da sessao
        db.refresh(admin)
        db.expunge(admin)

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_csrf] = lambda: None
    c = TestClient(app)

    with SessionLocal() as db:
        planta = buscar_ou_criar(c, prefixo, db, Plant, {"code": "P01"}, "/plants",
                                 {"code": "P01", "name": "Planta Industrial"})
        area = buscar_ou_criar(c, prefixo, db, Area, {"plant_id": uuid.UUID(planta), "code": "A01"},
                               "/areas", {"plant_id": planta, "code": "A01",
                                          "name": "Utilidades"})
        linha = buscar_ou_criar(c, prefixo, db, Line, {"area_id": uuid.UUID(area), "code": "L01"},
                                "/lines", {"area_id": area, "code": "L01",
                                           "name": "Linha de Utilidades"})

    agora = datetime.now(timezone.utc).replace(hour=9, minute=30, second=0, microsecond=0)

    for tag, nome, criticidade, coletas in MOTORES:
        r = c.post(prefixo + "/motors", json={
            "tag": tag, "name": nome, "line_id": linha, "criticality": criticidade,
            "rated_rpm": ROTACAO_RPM, "poles": 2, "iso_machine_class": "I", "notes": NOTA})
        r.raise_for_status()
        motor_id = r.json()["id"]
        print(f"\n{tag}  {nome}  (criticidade {criticidade})")

        dias = [45, 30, 15, 3][: len(coletas) + 1]
        p = enviar(c, prefixo, motor_id, REFERENCIA, dias[0], True, agora)
        print(f"    {REFERENCIA:22s} referencia")
        for sinal, d in zip(coletas, dias[1:]):
            p = enviar(c, prefixo, motor_id, sinal, d, False, agora)
            razao = p.get("ratio_to_baseline")
            print(f"    {sinal:22s} tipo={p['fault_type']:13s} severidade={p['severity']}"
                  + (f"  ({razao:.1f}x a referencia)" if razao else ""))

    print("\n[ok] motores de demonstracao criados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
