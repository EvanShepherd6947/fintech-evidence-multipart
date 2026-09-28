from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from payment_risk import decide_upload
from receipt_upload import Infrai, InfraiError


BUCKET = "fintech-payment-evidence"


class PaymentEvent(BaseModel):
    event_id: str = Field(min_length=3, max_length=120)
    payment_id: str = Field(min_length=3, max_length=120)
    amount_minor: Annotated[int, Field(gt=0)]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    risk_level: Literal["low", "medium", "high"]
    media_name: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=3, max_length=120)


class StartResult(BaseModel):
    action: Literal["multipart_upload", "manual_review"]
    payment_id: str
    audit_id: str
    occurred_at: datetime
    notification: str
    upload_id: str | None = None
    object_key: str | None = None


class PartRequest(BaseModel):
    event_id: str
    part_number: Annotated[int, Field(ge=1, le=10_000)]


class PartResult(BaseModel):
    upload_id: str
    part_number: int
    upload_method: Literal["PUT"] = "PUT"
    url: str


class CompletedPart(BaseModel):
    part_number: Annotated[int, Field(ge=1, le=10_000)]
    etag: str = Field(min_length=1)


class CompleteRequest(BaseModel):
    event_id: str
    parts: list[CompletedPart] = Field(min_length=1)


def _object_key(event: PaymentEvent) -> str:
    clean_name = event.media_name.replace("/", "_")
    return f"payments/{event.payment_id}/{event.event_id}/{clean_name}"


class EvidenceWorkflow:
    def __init__(self, infrai: Infrai, bucket: str = BUCKET) -> None:
        self.infrai = infrai
        self.bucket = bucket

    def prepare_bucket(self) -> None:
        self.infrai.storage.bucket.create(
            self.bucket, idempotency_key=f"bucket:{self.bucket}"
        )

    def start(self, event: PaymentEvent) -> StartResult:
        decision = decide_upload(event.risk_level, event.amount_minor)
        audit_id = f"audit:{event.event_id}"
        common: dict[str, Any] = {
            "action": decision.action,
            "payment_id": event.payment_id,
            "audit_id": audit_id,
            "occurred_at": datetime.now(timezone.utc),
            "notification": decision.reason,
        }
        if decision.action == "manual_review":
            return StartResult(**common)

        key = _object_key(event)
        created = self.infrai.storage.multipart.create(
            self.bucket,
            key,
            event.content_type,
            idempotency_key=f"start:{event.event_id}",
        )
        return StartResult(
            **common,
            upload_id=str(created["upload_id"]),
            object_key=key,
        )

    def sign_part(self, upload_id: str, request: PartRequest) -> PartResult:
        signed = self.infrai.storage.multipart.presign_part(
            upload_id,
            request.part_number,
            idempotency_key=f"part:{request.event_id}:{request.part_number}",
        )
        return PartResult(
            upload_id=upload_id,
            part_number=request.part_number,
            url=str(signed["url"]),
        )

    def complete(self, upload_id: str, request: CompleteRequest) -> dict[str, Any]:
        parts = [part.model_dump() for part in request.parts]
        return self.infrai.storage.multipart.complete(
            upload_id, parts, idempotency_key=f"complete:{request.event_id}"
        )

    def abort(self, upload_id: str) -> dict[str, Any]:
        return self.infrai.storage.multipart.abort(upload_id)


app = FastAPI(title="Payment evidence multipart service")


def workflow() -> EvidenceWorkflow:
    return EvidenceWorkflow(Infrai.from_environment())


def as_http_error(error: InfraiError) -> HTTPException:
    status = error.status_code if 400 <= error.status_code < 500 else 502
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})


@app.post("/setup", status_code=204)
def setup_bucket() -> None:
    try:
        workflow().prepare_bucket()
    except InfraiError as error:
        raise as_http_error(error) from error


@app.post("/payment-evidence", response_model=StartResult)
def start_payment_evidence(event: PaymentEvent) -> StartResult:
    try:
        return workflow().start(event)
    except InfraiError as error:
        raise as_http_error(error) from error


@app.post("/payment-evidence/{upload_id}/parts", response_model=PartResult)
def sign_payment_part(upload_id: str, request: PartRequest) -> PartResult:
    try:
        return workflow().sign_part(upload_id, request)
    except InfraiError as error:
        raise as_http_error(error) from error


@app.post("/payment-evidence/{upload_id}/complete")
def complete_payment_evidence(upload_id: str, request: CompleteRequest) -> dict[str, Any]:
    try:
        return workflow().complete(upload_id, request)
    except InfraiError as error:
        raise as_http_error(error) from error


@app.delete("/payment-evidence/{upload_id}")
def cancel_payment_evidence(upload_id: str) -> dict[str, Any]:
    try:
        return workflow().abort(upload_id)
    except InfraiError as error:
        raise as_http_error(error) from error
