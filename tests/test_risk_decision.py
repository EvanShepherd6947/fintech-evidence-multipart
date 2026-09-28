from payment_risk import decide_upload


def test_high_risk_payment_is_held_before_upload() -> None:
    result = decide_upload("high", 42_000)

    assert result.action == "manual_review"
    assert result.reason == "risk policy requires approval before media intake"


def test_large_payment_is_held_even_at_medium_risk() -> None:
    assert decide_upload("medium", 1_250_000).action == "manual_review"
