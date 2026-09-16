"""CRUD de motores.

A exclusao e SOFT: o motor sai do cadastro ativo mas o historico de medicoes e
previsoes permanece
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, audit, require_csrf
from app.core.errors import ProblemException
from app.database import get_db
from app.models.alert import Alert
from app.models.measurement import Measurement
from app.models.hierarchy import Line
from app.models.motor import Motor
from app.schemas.common import Page
from app.schemas.motor import MotorCreate, MotorDetail, MotorOut, MotorUpdate

router = APIRouter(tags=["motores"])
DbSession = Annotated[Session, Depends(get_db)]


def _preencher_caminho(detalhe: MotorDetail, motor: Motor) -> None:
    """Completa linha, area e planta a que o motor pertence."""
    linha = motor.line
    if linha is None:
        return
    detalhe.line_name = linha.name
    if linha.area:
        detalhe.area_name = linha.area.name
        if linha.area.plant:
            detalhe.plant_name = linha.area.plant.name


def _motor_ativo(db: Session, motor_id: uuid.UUID) -> Motor:
    motor = db.get(Motor, motor_id)
    if motor is None or motor.deleted_at is not None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Motor nao encontrado.")
    return motor


# ----------------------------------------------------------------- motores ---
@router.get("/motors", response_model=Page[MotorDetail])
def listar_motores(
    db: DbSession, user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    line_id: uuid.UUID | None = None,
    search: str | None = None,
    severity: str | None = Query(default=None, pattern="^(HEALTHY|WARNING|FAILURE)$"),
) -> Page[MotorDetail]:
    """Lista motores ativos com o resumo de condicao de cada um."""
    condicoes = [Motor.deleted_at.is_(None)]
    if line_id:
        condicoes.append(Motor.line_id == line_id)
    if search:
        termo = f"%{search.strip()}%"
        condicoes.append(Motor.tag.ilike(termo) | Motor.name.ilike(termo))

    total = db.scalar(select(func.count()).select_from(Motor).where(*condicoes)) or 0
    motores = list(db.scalars(
        select(Motor).where(*condicoes)
        .order_by(Motor.tag).limit(limit).offset(offset)))

    itens: list[MotorDetail] = []
    for motor in motores:
        ultima = db.scalar(
            select(Measurement).where(Measurement.motor_id == motor.id)
            .order_by(Measurement.created_at.desc()).limit(1))
        pred = ultima.prediction if ultima else None

        if severity and (pred is None or pred.severity != severity):
            continue

        detalhe = MotorDetail.model_validate(motor)
        _preencher_caminho(detalhe, motor)
        detalhe.measurement_count = db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.motor_id == motor.id)) or 0
        detalhe.last_measurement_at = ultima.collected_at if ultima else None
        detalhe.last_severity = pred.severity if pred else None
        detalhe.last_fault_type = pred.fault_type if pred else None
        detalhe.last_is_baseline = bool(ultima and ultima.is_baseline)
        detalhe.open_alerts = db.scalar(
            select(func.count()).select_from(Alert)
            .where(Alert.motor_id == motor.id, Alert.status == "OPEN")) or 0
        detalhe.max_priority = float(db.scalar(
            select(func.max(Alert.priority_score))
            .where(Alert.motor_id == motor.id, Alert.status == "OPEN")) or 0.0)
        detalhe.has_baseline = motor.baseline_measurement_id is not None
        itens.append(detalhe)

    return Page(items=itens, total=total, limit=limit, offset=offset)


@router.post("/motors", response_model=MotorOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_csrf)])
def criar_motor(payload: MotorCreate, request: Request, db: DbSession,
                user: CurrentUser) -> Motor:
    existente = db.scalar(select(Motor).where(Motor.tag == payload.tag))
    if existente:
        if existente.deleted_at is None:
            raise ProblemException(
                status.HTTP_409_CONFLICT, "Conflito",
                f"Ja existe um motor com a tag '{payload.tag}'.")
        raise ProblemException(
            status.HTTP_409_CONFLICT, "Conflito",
            f"A tag '{payload.tag}' pertence a um motor removido. "
            f"Restaure-o ou use outra tag.")

    if payload.line_id:
        linha = db.get(Line, payload.line_id)
        if linha is None or linha.deleted_at is not None:
            raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                                   "Linha informada nao existe.")

    motor = Motor(**payload.model_dump())
    db.add(motor)
    db.flush()
    audit(db, request, user, "motor_created", "motors", motor.id, tag=motor.tag)
    db.commit()
    db.refresh(motor)
    return motor


@router.get("/motors/{motor_id}", response_model=MotorDetail)
def obter_motor(motor_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MotorDetail:
    motor = _motor_ativo(db, motor_id)
    ultima = db.scalar(
        select(Measurement).where(Measurement.motor_id == motor.id)
        .order_by(Measurement.created_at.desc()).limit(1))
    pred = ultima.prediction if ultima else None

    detalhe = MotorDetail.model_validate(motor)
    _preencher_caminho(detalhe, motor)
    detalhe.measurement_count = db.scalar(
        select(func.count()).select_from(Measurement)
        .where(Measurement.motor_id == motor.id)) or 0
    detalhe.last_measurement_at = ultima.collected_at if ultima else None
    detalhe.last_severity = pred.severity if pred else None
    detalhe.last_fault_type = pred.fault_type if pred else None
    detalhe.last_is_baseline = bool(ultima and ultima.is_baseline)
    detalhe.open_alerts = db.scalar(
        select(func.count()).select_from(Alert)
        .where(Alert.motor_id == motor.id, Alert.status == "OPEN")) or 0
    detalhe.max_priority = float(db.scalar(
        select(func.max(Alert.priority_score))
        .where(Alert.motor_id == motor.id, Alert.status == "OPEN")) or 0.0)
    detalhe.has_baseline = motor.baseline_measurement_id is not None
    return detalhe


@router.put("/motors/{motor_id}", response_model=MotorOut,
            dependencies=[Depends(require_csrf)])
def atualizar_motor(motor_id: uuid.UUID, payload: MotorUpdate, request: Request,
                    db: DbSession, user: CurrentUser) -> Motor:
    motor = _motor_ativo(db, motor_id)
    mudancas = payload.model_dump(exclude_unset=True)

    if mudancas.get("line_id") is not None:
        linha = db.get(Line, mudancas["line_id"])
        if linha is None or linha.deleted_at is not None:
            raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                                   "Linha informada nao existe.")

    # a medicao de referencia precisa ser deste motor
    if mudancas.get("baseline_measurement_id"):
        medicao = db.get(Measurement, mudancas["baseline_measurement_id"])
        if medicao is None or medicao.motor_id != motor.id:
            raise ProblemException(
                status.HTTP_400_BAD_REQUEST, "Requisicao invalida",
                "A medicao de referencia deve pertencer a este motor.")
        medicao.is_baseline = True

    for campo, valor in mudancas.items():
        setattr(motor, campo, valor)

    audit(db, request, user, "motor_updated", "motors", motor.id,
          fields=sorted(mudancas))
    db.commit()
    db.refresh(motor)
    return motor


@router.delete("/motors/{motor_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_csrf)])
def remover_motor(motor_id: uuid.UUID, request: Request, db: DbSession,
                  user: CurrentUser) -> None:
    """Soft delete: preserva medicoes, previsoes e alertas do motor."""
    motor = _motor_ativo(db, motor_id)
    motor.deleted_at = datetime.now(timezone.utc)
    audit(db, request, user, "motor_deleted", "motors", motor.id, tag=motor.tag)
    db.commit()
