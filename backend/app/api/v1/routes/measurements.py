"""Medicoes e inferencia sincrona.

O tecnico envia o sinal coletado em campo e recebe o diagnostico na MESMA
requisicao — sem fila, sem polling. A escolha e deliberada: em campo,
precisa saber se deve agir antes de sair de perto da maquina.
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Annotated

import numpy as np

from fastapi import (
    APIRouter, Depends, File, Form, Query, Request, UploadFile, status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import alert_policy
from app.core.deps import CurrentUser, audit, require_csrf
from app.core.errors import ProblemException
from app.database import get_db
from app.ml.predictor import ModelNotAvailable, get_predictor
from config import MS2_TO_G  # noqa: E402
from signals.readers import SignalReadError, read_signal  # noqa: E402
from app.models.alert import Alert, Inspection
from app.models.measurement import Measurement, Prediction
from app.models.ml_model import MLModel
from app.models.motor import Motor
from app.schemas.common import Page
from app.schemas.waveform import WaveformOut, WaveformPoint
from app.schemas.measurement import (
    MeasurementContext,
    MeasurementListItem,
    MeasurementWithPrediction,
    PredictionOut,
)

settings = get_settings()
router = APIRouter(tags=["medicoes"])
DbSession = Annotated[Session, Depends(get_db)]

_NOME_SEGURO = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(nome: str) -> str:
    """Neutraliza travessia de diretorio no nome enviado pelo cliente.

    Guarda-se apenas o nome base, sem separadores, e o arquivo e gravado com um
    UUID proprio — o nome original serve so para exibicao.
    """
    base = nome.replace("\\", "/").split("/")[-1]
    limpo = _NOME_SEGURO.sub("_", base).lstrip(".")
    return limpo[:200] or "sinal"


async def _receber_arquivo(upload: UploadFile) -> tuple[bytes, str, str]:
    """Le o upload validando extensao e tamanho. Retorna (bytes, nome, sha256)."""
    nome = _sanitize_filename(upload.filename or "sinal")
    sufixo = ("." + nome.rsplit(".", 1)[-1].lower()) if "." in nome else ""

    if sufixo not in settings.upload_suffixes:
        raise ProblemException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Formato nao suportado",
            f"Extensao '{sufixo or 'ausente'}' nao aceita. "
            f"Formatos: {', '.join(sorted(settings.upload_suffixes))}.")

    limite = settings.max_upload_mb * 1024 * 1024
    pedacos, tamanho, digest = [], 0, hashlib.sha256()
    while pedaco := await upload.read(1 << 20):
        tamanho += len(pedaco)
        if tamanho > limite:
            raise ProblemException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Conteudo grande demais",
                f"Arquivo excede o limite de {settings.max_upload_mb} MB.")
        digest.update(pedaco)
        pedacos.append(pedaco)

    if tamanho == 0:
        raise ProblemException(status.HTTP_400_BAD_REQUEST, "Requisicao invalida",
                               "Arquivo vazio.")
    return b"".join(pedacos), nome, digest.hexdigest()


def _modelo_registrado(db: Session, versao: str) -> MLModel:
    modelo = db.scalar(select(MLModel).where(MLModel.version == versao))
    if modelo is None:
        raise ProblemException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Erro interno",
            f"O modelo '{versao}' nao esta registrado em ml_models. "
            f"Execute backend/scripts/register_models.py.")
    return modelo


def _abrir_alerta(db: Session, motor: Motor, pred: Prediction,
                  medicao: Measurement, modelo_id, anterior: dict | None) -> Alert | None:
    """Aplica a politica de alertas (app/core/alert_policy.py).

    Toda a decisao — se alerta, com que severidade e com que prioridade — vem da
    politica, que grava a REGRA que disparou. Nenhuma condicao fica implicita
    aqui dentro.
    """
    decisao = alert_policy.evaluate(
        severity=pred.severity,
        fault_type=pred.fault_type,
        confidence=pred.confidence,
        evidence_agreement=pred.evidence_agreement,
        physical_type=pred.physical_type,
        iso_zone=medicao.iso_zone,
        indicators={k: v for k, v in {
            "iso_v_rms_mms": medicao.iso_v_rms_mms,
            "iso_v_1x_mms": medicao.iso_v_1x_mms,
            "iso_v_2x_mms": medicao.iso_v_2x_mms,
            "iso_a_hf_g": medicao.iso_a_hf_g,
        }.items() if v is not None},
        baseline_comparison=pred.baseline_comparison,
        previous_indicators=anterior,
        criticality=motor.criticality,
        motor_tag=motor.tag,
        is_baseline=medicao.is_baseline,
    )
    if not decisao.should_alert:
        return None

    alerta = Alert(
        motor_id=motor.id, prediction_id=pred.id, ml_model_id=modelo_id,
        severity=decisao.severity, status="OPEN", message=decisao.message,
        rule=str(decisao.rule), reasons=decisao.reasons,
        priority_score=decisao.priority_score,
        fault_type=pred.fault_type, physical_type=pred.physical_type,
        confidence=pred.confidence, evidence_agreement=pred.evidence_agreement,
        trend_pct=decisao.trend_pct,
        indicators={
            "iso_v_rms_mms": medicao.iso_v_rms_mms,
            "iso_a_hf_g": medicao.iso_a_hf_g,
            "iso_zone": medicao.iso_zone,
        },
    )
    db.add(alerta)
    return alerta


def _indicadores_anteriores(db: Session, motor_id, exceto_id) -> dict | None:
    """Indicadores da medicao imediatamente anterior, para calculo de tendencia."""
    anterior = db.scalar(
        select(Measurement)
        .where(Measurement.motor_id == motor_id, Measurement.id != exceto_id)
        .order_by(Measurement.created_at.desc()).limit(1))
    if anterior is None:
        return None
    return {k: v for k, v in {
        "iso_v_rms_mms": anterior.iso_v_rms_mms,
        "iso_a_hf_g": anterior.iso_a_hf_g,
    }.items() if v is not None}


@router.post("/measurements", response_model=MeasurementWithPrediction,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_csrf)])
async def criar_medicao(
    request: Request, db: DbSession, user: CurrentUser,
    file: Annotated[UploadFile, File(description="arquivo de sinal de vibracao")],
    context: Annotated[str, Form(description="JSON com os dados do formulario")],
    current_file: Annotated[UploadFile | None, File(
        description="arquivo de corrente, opcional. Quando enviado junto com um "
                    "sinal de 4 canais, habilita o perfil completo")] = None,
) -> MeasurementWithPrediction:
    """Recebe o sinal, diagnostica e grava — respondendo na mesma requisicao.

    O perfil de modelo e escolhido pelo que foi enviado: 4 canais de vibracao
    mais corrente ativam `kaist_full`; um canal de vibracao ativa `field_single`.
    """
    from pydantic import ValidationError

    try:
        ctx = MeasurementContext.model_validate_json(context)
    except ValidationError as exc:
        raise ProblemException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Dados invalidos",
            "Campo 'context' invalido.",
            errors=[{"campo": ".".join(str(p) for p in e["loc"]),
                     "mensagem": e["msg"]} for e in exc.errors()]) from None

    motor = db.get(Motor, ctx.motor_id)
    if motor is None or motor.deleted_at is not None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Motor nao encontrado.")

    conteudo, nome_original, digest = await _receber_arquivo(file)

    # grava com nome proprio; o nome do cliente nunca compoe o caminho em disco
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    sufixo = "." + nome_original.rsplit(".", 1)[-1].lower()
    destino = settings.upload_dir / f"{uuid.uuid4()}{sufixo}"
    destino.write_bytes(conteudo)

    hints = {"sample_rate_hz": ctx.sample_rate_hz, "unit": ctx.unit}
    try:
        sinal = read_signal(destino, **{k: v for k, v in hints.items() if v})
    except SignalReadError as exc:
        destino.unlink(missing_ok=True)
        raise ProblemException(status.HTTP_400_BAD_REQUEST,
                               "Requisicao invalida", str(exc)) from None

    if ctx.channel >= sinal.n_channels:
        destino.unlink(missing_ok=True)
        raise ProblemException(
            status.HTTP_400_BAD_REQUEST, "Requisicao invalida",
            f"Canal {ctx.channel} inexistente: o arquivo tem "
            f"{sinal.n_channels} canal(is).")

    # arquivo de corrente opcional: habilita o perfil completo quando presente
    sinal_corrente, destino_corrente = None, None
    if current_file is not None and current_file.filename:
        conteudo_c, nome_c, _ = await _receber_arquivo(current_file)
        sufixo_c = "." + nome_c.rsplit(".", 1)[-1].lower()
        destino_corrente = settings.upload_dir / f"{uuid.uuid4()}{sufixo_c}"
        destino_corrente.write_bytes(conteudo_c)
        try:
            sinal_corrente = read_signal(
                destino_corrente, **{k: v for k, v in hints.items() if v})
        except SignalReadError as exc:
            destino.unlink(missing_ok=True)
            destino_corrente.unlink(missing_ok=True)
            raise ProblemException(
                status.HTTP_400_BAD_REQUEST, "Requisicao invalida",
                f"arquivo de corrente: {exc}") from None

    baseline_ind = None
    if motor.baseline_measurement_id:
        ref = db.get(Measurement, motor.baseline_measurement_id)
        if ref:
            baseline_ind = {k: getattr(ref, k) for k in
                            ("iso_v_rms_mms", "iso_v_1x_mms", "iso_v_2x_mms",
                             "iso_a_hf_g") if getattr(ref, k) is not None}

    try:
        # As features de 1x, 2x e 3x so fazem sentido na rotacao do eixo medido.
        # Prevalece a rotacao informada na coleta (condicao do momento) sobre a
        # nominal do cadastro. Sem nenhuma das duas, cai no padrao da bancada.
        rpm = ctx.rpm or motor.rated_rpm
        resultado = get_predictor().predict(
            sinal, channel=ctx.channel, current=sinal_corrente, load_nm=ctx.load_nm,
            baseline=baseline_ind or None, machine_class=motor.iso_machine_class,
            rot_hz=(rpm / 60.0) if rpm else None)
    except ModelNotAvailable as exc:
        destino.unlink(missing_ok=True)
        if destino_corrente:
            destino_corrente.unlink(missing_ok=True)
        raise ProblemException(status.HTTP_503_SERVICE_UNAVAILABLE,
                               "Erro interno", str(exc)) from None
    except ValueError as exc:
        destino.unlink(missing_ok=True)
        if destino_corrente:
            destino_corrente.unlink(missing_ok=True)
        raise ProblemException(status.HTTP_400_BAD_REQUEST,
                               "Requisicao invalida", str(exc)) from None

    modelo = _modelo_registrado(db, resultado.model_version)

    medicao = Measurement(
        motor_id=motor.id, user_id=user.id,
        collected_at=ctx.collected_at or datetime.now(timezone.utc),
        load_nm=ctx.load_nm, rpm=ctx.rpm,
        temperature_c=ctx.temperature_c, voltage_v=ctx.voltage_v,
        current_a=ctx.current_a, operating_hours=ctx.operating_hours,
        is_baseline=ctx.is_baseline,
        source_filename=nome_original, source_path=str(destino),
        source_unit=ctx.unit,
        source_sha256=digest,
        sample_rate_hz=sinal.sample_rate, n_samples=sinal.n_samples,
        n_channels=sinal.n_channels, duration_s=sinal.duration_s,
        features=resultado.features,
        iso_v_rms_mms=resultado.indicators.get("iso_v_rms_mms"),
        iso_v_1x_mms=resultado.indicators.get("iso_v_1x_mms"),
        iso_v_2x_mms=resultado.indicators.get("iso_v_2x_mms"),
        iso_a_hf_g=resultado.indicators.get("iso_a_hf_g"),
        iso_zone=resultado.iso_zone,
        notes=ctx.notes,
    )
    db.add(medicao)
    db.flush()

    predicao = Prediction(
        measurement_id=medicao.id, ml_model_id=modelo.id,
        # severidade por criterio fisico (primaria)
        severity=resultado.severity,
        severity_criterion=resultado.severity_criterion,
        severity_explanation=resultado.severity_explanation,
        ratio_to_baseline=resultado.ratio_to_baseline,
        # severidade do modelo (experimento preliminar, informativa)
        ml_severity=resultado.ml_severity,
        severity_probabilities=resultado.ml_severity_probabilities,
        fault_type=resultado.fault_type,
        fault_type_probabilities=resultado.fault_type_probabilities,
        physical_type=resultado.physical_type,
        evidence_agreement=resultado.evidence_agreement,
        confidence=resultado.confidence,
        recommendation=f"{resultado.recommendation} {resultado.severity_explanation}",
        top_factors=resultado.top_factors,
        baseline_comparison=resultado.baseline_comparison,
        inference_ms=resultado.inference_ms,
    )
    db.add(predicao)
    db.flush()

    if ctx.is_baseline:
        motor.baseline_measurement_id = medicao.id

    anterior = _indicadores_anteriores(db, motor.id, medicao.id)
    alerta = _abrir_alerta(db, motor, predicao, medicao, modelo.id, anterior)
    db.flush()

    audit(db, request, user, "measurement_created", "measurements", medicao.id,
          motor_tag=motor.tag, severity=predicao.severity,
          model_version=modelo.version)
    db.commit()
    db.refresh(medicao)
    db.refresh(predicao)

    saida = MeasurementWithPrediction.model_validate(medicao)
    saida.prediction = PredictionOut.model_validate(predicao)
    saida.model_version = modelo.version
    saida.profile = resultado.profile
    if resultado.profile == "field_single":
        saida.profile_note = (
            "Diagnostico por canal unico: alta sensibilidade a falha (93,7%) e "
            "baixa especificidade (23,3%). Adequado a triagem; condicao normal "
            "nao e conclusiva.")
    saida.alert_id = alerta.id if alerta else None
    return saida


@router.get("/motors/{motor_id}/measurements", response_model=Page[MeasurementListItem])
def historico_medicoes(
    motor_id: uuid.UUID, db: DbSession, user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MeasurementListItem]:
    """Historico do motor, do mais recente para o mais antigo.

    Usa o indice composto (motor_id, created_at).
    """
    if db.get(Motor, motor_id) is None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Motor nao encontrado.")

    total = db.scalar(select(func.count()).select_from(Measurement)
                      .where(Measurement.motor_id == motor_id)) or 0
    itens = list(db.scalars(
        select(Measurement).where(Measurement.motor_id == motor_id)
        .order_by(Measurement.created_at.desc()).limit(limit).offset(offset)))
    # quais previsoes ja foram confirmadas em campo, para a tela nao oferecer
    # registrar a mesma inspecao duas vezes
    inspecionadas = set(db.scalars(
        select(Inspection.prediction_id)
        .where(Inspection.prediction_id.is_not(None))).all())

    linhas = []
    for m in itens:
        linha = MeasurementListItem.model_validate(m)
        if m.prediction:
            linha.prediction_id = m.prediction.id
            linha.fault_type = m.prediction.fault_type
            linha.severity = m.prediction.severity
            linha.inspected = m.prediction.id in inspecionadas
        linhas.append(linha)

    return Page(items=linhas, total=total, limit=limit, offset=offset)


@router.get("/motors/{motor_id}/predictions", response_model=Page[PredictionOut])
def historico_previsoes(
    motor_id: uuid.UUID, db: DbSession, user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PredictionOut]:
    if db.get(Motor, motor_id) is None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Motor nao encontrado.")

    base = (select(Prediction).join(Measurement)
            .where(Measurement.motor_id == motor_id))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    itens = list(db.scalars(
        base.order_by(Prediction.created_at.desc()).limit(limit).offset(offset)))
    return Page(items=[PredictionOut.model_validate(p) for p in itens],
                total=total, limit=limit, offset=offset)


@router.get("/measurements/{measurement_id}", response_model=MeasurementWithPrediction)
def obter_medicao(measurement_id: uuid.UUID, db: DbSession,
                  user: CurrentUser) -> MeasurementWithPrediction:
    medicao = db.get(Measurement, measurement_id)
    if medicao is None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Medicao nao encontrada.")
    saida = MeasurementWithPrediction.model_validate(medicao)
    if medicao.prediction:
        saida.prediction = PredictionOut.model_validate(medicao.prediction)
        saida.model_version = medicao.prediction.ml_model.version
    return saida


@router.get("/measurements/{measurement_id}/waveform", response_model=WaveformOut)
def forma_de_onda(
    measurement_id: uuid.UUID, db: DbSession, user: CurrentUser,
    channel: Annotated[int, Query(ge=0, le=15)] = 0,
    max_points: Annotated[int, Query(ge=200, le=4000)] = 1200,
) -> WaveformOut:
    """Forma de onda do sinal, reduzida para exibicao.

    A reducao e por ENVELOPE (min e max de cada balde), nao por amostragem. Em
    vibracao o conteudo diagnostico esta em picos curtos: o impacto de um
    defeito de pista dura microssegundos. Pegar uma amostra a cada N descartaria
    esses picos e desenharia um sinal mais limpo do que o medido — um erro que
    ninguem percebe olhando o grafico.

    Os escalares (pico a pico, pico, RMS) vem do sinal INTEIRO, nao dos pontos
    devolvidos, para que o numero exibido nao dependa da resolucao do grafico.
    """
    medicao = db.get(Measurement, measurement_id)
    if medicao is None:
        raise ProblemException(status.HTTP_404_NOT_FOUND, "Recurso nao encontrado",
                               "Medicao nao encontrada.")

    if not medicao.source_path or not Path(medicao.source_path).exists():
        raise ProblemException(
            status.HTTP_410_GONE, "Sinal indisponivel",
            "O arquivo bruto desta medicao nao esta mais armazenado. Os "
            "indicadores e o diagnostico permanecem no historico.")

    try:
        sinal = read_signal(
            Path(medicao.source_path),
            sample_rate_hz=medicao.sample_rate_hz,
            # a mesma unidade declarada no envio, para que o grafico fique na
            # mesma escala das features gravadas; sem registro, o leitor assume
            # m/s^2, que e o padrao do proprio envio
            **({"unit": medicao.source_unit} if medicao.source_unit else {}))
    except SignalReadError as e:
        raise ProblemException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                               "Sinal ilegivel", str(e)) from e

    if channel >= sinal.n_channels:
        raise ProblemException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Canal inexistente",
            f"O sinal tem {sinal.n_channels} canal(is); pedido o indice {channel}.")

    # analise em g, que e a unidade em que o tecnico le aceleracao
    x = sinal.samples[:, channel].astype(float) * MS2_TO_G
    x = x - x.mean()                      # o offset DC nao e vibracao
    n = len(x)

    rms = float(np.sqrt(np.mean(x**2)))
    pico = float(np.abs(x).max())

    fator = max(1, ceil(n / max_points))
    util = (n // fator) * fator
    blocos = x[:util].reshape(-1, fator)
    tempos = np.arange(len(blocos)) * fator / sinal.sample_rate

    return WaveformOut(
        measurement_id=str(measurement_id),
        channel=channel,
        channel_name=sinal.channel_names[channel],
        unit="g",
        sample_rate_hz=sinal.sample_rate,
        n_samples=n,
        duration_s=n / sinal.sample_rate,
        decimation=fator,
        points=[WaveformPoint(t=round(float(t), 5),
                              min=round(float(b.min()), 5),
                              max=round(float(b.max()), 5))
                for t, b in zip(tempos, blocos, strict=True)],
        peak_to_peak_g=round(float(x.max() - x.min()), 5),
        peak_g=round(pico, 5),
        rms_g=round(rms, 5),
        crest_factor=round(pico / rms, 3) if rms else 0.0,
    )
