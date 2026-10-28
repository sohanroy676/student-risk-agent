"""Admin endpoints for the model registry: releases, their gate results, and promotion.

Admin only. Everything returned is an aggregate (AUC, calibration error, recall gaps by group);
no student-level number leaves here. The person promoting is the token's subject, and a block
can only be accepted by a sign-off that lists it; missing or unassessed numbers cannot be.
"""

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Connection

from app.api.deps import get_conn, require_roles
from app.core import audit_store
from app.core.auth import Principal, Role
from app.core.settings import get_settings
from app.ml.gate import GateResult, SignOff
from app.ml.registry import AlreadyProduction, NoSuchRelease, Registry, ReleaseInfo

MAX_RELEASE = 2**31 - 1
MAX_COVERS = 20

router = APIRouter(prefix="/api/admin/models", tags=["models"])

Conn = Annotated[Connection, Depends(get_conn, scope="function")]
Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]
Release = Annotated[int, PathParam(ge=1, le=MAX_RELEASE)]
BlockCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z_]{1,40}(:[A-Za-z0-9_]{1,40})?$")
]


def get_registry() -> Registry:
    return Registry(Path(get_settings().model_store))


Reg = Annotated[Registry, Depends(get_registry)]


class MetricsOut(BaseModel):
    auc_week4: float | None
    ece: float | None
    recall_gaps: dict[str, float | None]


class GateOut(BaseModel):
    passed: bool
    blocks: list[str]
    hard_failures: list[str]
    overridden: list[str]
    signed_off_by: str | None


class ReleaseOut(BaseModel):
    release: int
    created: str
    weeks: list[int]
    in_production: bool
    metrics: MetricsOut | None
    gate_now: GateOut | None  # what the gate says today, with no sign-off
    gate_recorded: dict[str, Any] | None  # the verdict stored when the gate last ran
    sign_off: dict[str, str] | None


class ModelCard(BaseModel):
    release: int
    markdown: str


class PromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=1000)] = ""
    covers: Annotated[list[BlockCode], Field(max_length=MAX_COVERS)] = []


def _clean(value: float) -> float | None:
    return None if math.isnan(value) else value


def _gate_out(result: GateResult) -> GateOut:
    return GateOut(
        passed=result.passed,
        blocks=list(result.blocks),
        hard_failures=list(result.hard_failures),
        overridden=list(result.overridden),
        signed_off_by=result.signed_off_by,
    )


def _describe(registry: Registry, info: ReleaseInfo) -> ReleaseOut:
    metrics = gate_now = None
    if info.metrics is not None:
        m = info.metrics
        metrics = MetricsOut(
            auc_week4=_clean(m.auc_week4),
            ece=_clean(m.ece),
            recall_gaps={k: _clean(v) for k, v in sorted(m.recall_gaps.items())},
        )
        if not info.production:
            try:
                gate_now = _gate_out(registry.assess(info))
            except ValueError:  # the production model has no recorded metrics to compare with
                gate_now = None
    return ReleaseOut(
        release=info.release,
        created=datetime.fromtimestamp(info.created_ms / 1000, UTC).isoformat(),
        weeks=sorted(info.versions),
        in_production=info.production,
        metrics=metrics,
        gate_now=gate_now,
        gate_recorded=dict(info.gate) if info.gate is not None else None,
        sign_off=dict(info.sign_off) if info.sign_off is not None else None,
    )


def _find(registry: Registry, number: int) -> ReleaseInfo:
    try:
        return registry.release(number)
    except NoSuchRelease:
        raise HTTPException(status_code=404, detail="release not found") from None


@router.get("")
def list_releases(
    _: Admin, registry: Reg, limit: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[ReleaseOut]:
    """Registered releases, newest first."""
    return [_describe(registry, info) for info in registry.releases()[:limit]]


@router.get("/{release}")
def get_release(release: Release, _: Admin, registry: Reg) -> ReleaseOut:
    return _describe(registry, _find(registry, release))


@router.get("/{release}/card")
def get_model_card(release: Release, _: Admin, registry: Reg) -> ModelCard:
    info = _find(registry, release)
    return ModelCard(release=info.release, markdown=registry.card(info))


@router.post("/{release}/promote")
def promote_release(
    release: Release, body: PromoteRequest, principal: Admin, conn: Conn, registry: Reg
) -> GateOut:
    """Move the production alias to a release if the gate passes, with a sign-off if needed.

    The sign-off is made in the caller's name and lists exactly the blocks accepted. A refusal
    changes nothing. The audit entry is written first, in the same transaction, so a failed
    promotion rolls it back.
    """
    info = _find(registry, release)
    if info.production:
        raise HTTPException(status_code=409, detail="release is already in production")
    sign_off = None
    if body.covers:
        try:
            sign_off = SignOff(principal.subject, body.reason, frozenset(body.covers))
        except ValueError:
            raise HTTPException(status_code=422, detail="a sign-off needs a reason") from None
    try:
        verdict = registry.assess(info, sign_off)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if not verdict.passed:
        raise HTTPException(
            status_code=409,
            detail={
                "unresolved": list(verdict.unresolved),
                "hard_failures": list(verdict.hard_failures),
            },
        )
    audit_store.append(
        conn,
        actor_kind=principal.role.value,
        actor_id=principal.subject,
        action="model.promoted",
        subject_kind="model",
        subject_ref=f"release-{info.release}",
        detail={"release": info.release, "overridden": list(verdict.overridden)},
    )
    try:
        result = registry.promote_release(info, sign_off)
    except AlreadyProduction:
        raise HTTPException(status_code=409, detail="release is already in production") from None
    return _gate_out(result)
