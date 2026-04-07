from app.services.reason_codes import QAReasonCode, normalize_reason_code


def test_reason_code_normalization_from_legacy_values():
    assert normalize_reason_code("no_candidates") == QAReasonCode.NO_RETRIEVAL_HIT
    assert normalize_reason_code("low_confidence_retrieval") == QAReasonCode.LOW_RETRIEVAL_CONFIDENCE


def test_reason_code_normalization_from_new_values():
    assert normalize_reason_code("internal_error") == QAReasonCode.INTERNAL_ERROR
