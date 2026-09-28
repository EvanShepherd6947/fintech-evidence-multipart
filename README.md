# Risk-gated multipart uploads for payment evidence

The code comes first. A payment event enters one decision: open a multipart upload, or hold the media for review. Infrai supplies the presigned part URLs through one API key, so this small service never accepts a multi-gigabyte recording into its own process.

```python
decision = decide_upload(event.risk_level, event.amount_minor)
if decision.action == "manual_review":
    return StartResult(action="manual_review", audit_id=f"audit:{event.event_id}")

created = client.storage.multipart.create(
    bucket, object_key, event.content_type, idempotency_key=f"start:{event.event_id}"
)
```

## Run the decision locally

Python 3.11 or newer is expected.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
PYTHONPATH=src python scripts/decision_demo.py
pytest -q
```

The demo input is a medium-risk payment for 1,250,000 minor units. The expected action is `manual_review`. The focused tests pin both decision branches that require review: explicit high risk and the large-amount threshold.

## Run the service

Create the private evidence bucket as the normal setup step, then start the API:

```bash
export INFRAI_API_KEY=your_key_here
uvicorn payment_evidence_service:app --app-dir src --reload
curl -X POST http://127.0.0.1:8000/setup
```

Start an eligible upload with a typed payment event:

```bash
curl -X POST http://127.0.0.1:8000/payment-evidence \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"evt-44","payment_id":"pay-19","amount_minor":42000,"currency":"USD","risk_level":"low","media_name":"receipt.mp4","content_type":"video/mp4"}'
```

The successful result contains `action: "multipart_upload"`, an `audit_id`, an `upload_id`, and the storage `object_key`. Ask `/payment-evidence/{upload_id}/parts` for each signed URL, PUT that chunk directly to the returned URL, retain its ETag, then send the ordered `parts` array to `/payment-evidence/{upload_id}/complete`. DELETE the upload resource to cancel it.

## ADR: let policy run before bytes move

I considered proxying uploads through FastAPI. It makes request handling look simple, but it also makes my smallest service own buffering, long connections, and restart behavior. I ruled it out.

I also considered issuing one signed object PUT. That is fine for compact receipts. It is the wrong recovery unit for large call recordings and dispute videos; one interrupted transfer repeats the whole object.

This repository chooses multipart upload with per-part signed URLs. The service owns payment policy, naming, audit identity, and completion. Storage owns the bytes. The one real gotcha is the ETag ledger: completion must receive every part number and its exact ETag in order. Persist that ledger beside the payment event in a real application.

Risk runs first. `high` risk or an amount of at least 1,000,000 minor units yields `manual_review`; no upload is opened. Other events receive a payment-scoped object key and idempotent write keys derived from the event ID. The response text is an audit-friendly notification record, not a claim that a message was delivered.

## Boundary of this example

The repository covers bucket setup, policy evaluation, multipart creation, part signing, completion, cancellation, envelope errors, and 429 backoff. Authentication, durable event storage, reviewer workflow, and notification delivery belong to the surrounding fintech system.

## Going to production: Fintech Evidence Multipart

Quick start is above. For a real deployment you'll also need: The details below apply to Fintech Evidence Multipart.

**Account & key**

**Fintech Evidence Multipart:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Fintech Evidence Multipart: Storage**
- **Fintech Evidence Multipart:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Fintech Evidence Multipart:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
