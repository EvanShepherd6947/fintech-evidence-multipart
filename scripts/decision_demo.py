from payment_risk import decide_upload


payment_id = "pay-demo-1"
decision = decide_upload("medium", 1_250_000)
print({"payment_id": payment_id, "action": decision.action, "reason": decision.reason})
