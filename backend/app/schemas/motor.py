"""Schemas de motor."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MotorBase(BaseModel):
    tag: str = Field(min_length=1, max_length=60,
                     description="identificacao do motor na planta, ex. MT-101")
    name: str = Field(min_length=2, max_length=160)
    line_id: uuid.UUID | None = None

    criticality: str = Field(
        default="B", pattern="^[ABC]$",
        description="criticidade para a producao: A=parada de linha, "
                    "B=impacto parcial, C=redundante")

    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)

    # Faixas de placa plausiveis para motores industriais. Servem tambem de base
    # para a validacao de range das medicoes.
    power_kw: float | None = Field(default=None, gt=0, le=10_000)
    rated_rpm: int | None = Field(default=None, gt=0, le=60_000)
    poles: int | None = Field(default=None, ge=2, le=48)
    rated_current_a: float | None = Field(default=None, gt=0, le=10_000)
    rated_voltage_v: float | None = Field(default=None, gt=0, le=50_000)

    iso_machine_class: str = Field(default="I", pattern="^(I|II|III|IV)$",
                                   description="classe de maquina da ISO 10816-1")
    foundation_type: str | None = Field(
        default=None, pattern="^(RIGID|FLEXIBLE)$",
        description="rigidez da fundacao; distingue as classes III e IV")
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("tag")
    @classmethod
    def _tag_limpa(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("tag nao pode ser vazia")
        return v

    @field_validator("poles")
    @classmethod
    def _polos_pares(cls, v: int | None) -> int | None:
        if v is not None and v % 2 != 0:
            raise ValueError("numero de polos deve ser par")
        return v


class MotorCreate(MotorBase):
    pass


class MotorUpdate(BaseModel):
    """Atualizacao parcial: apenas os campos enviados sao alterados."""

    name: str | None = Field(default=None, min_length=2, max_length=160)
    line_id: uuid.UUID | None = None
    criticality: str | None = Field(default=None, pattern="^[ABC]$")
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    power_kw: float | None = Field(default=None, gt=0, le=10_000)
    rated_rpm: int | None = Field(default=None, gt=0, le=60_000)
    poles: int | None = Field(default=None, ge=2, le=48)
    rated_current_a: float | None = Field(default=None, gt=0, le=10_000)
    rated_voltage_v: float | None = Field(default=None, gt=0, le=50_000)
    iso_machine_class: str | None = Field(default=None, pattern="^(I|II|III|IV)$")
    foundation_type: str | None = Field(default=None, pattern="^(RIGID|FLEXIBLE)$")
    notes: str | None = Field(default=None, max_length=4000)
    baseline_measurement_id: uuid.UUID | None = None


class MotorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tag: str
    name: str
    line_id: uuid.UUID | None
    criticality: str
    manufacturer: str | None
    model: str | None
    power_kw: float | None
    rated_rpm: int | None
    poles: int | None
    rated_current_a: float | None
    rated_voltage_v: float | None
    iso_machine_class: str
    foundation_type: str | None
    baseline_measurement_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class MotorDetail(MotorOut):
    """Motor com o resumo de condicao usado no dashboard."""

    line_name: str | None = None
    area_name: str | None = None
    plant_name: str | None = None
    measurement_count: int = 0
    last_measurement_at: datetime | None = None
    last_severity: str | None = None
    last_fault_type: str | None = None
    last_is_baseline: bool = False
    open_alerts: int = 0
    max_priority: float = 0.0
    has_baseline: bool = False
