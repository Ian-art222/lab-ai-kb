import unittest

from app.api.qa import _map_qa_error_to_reason
from app.services.ingest_service import resolve_index_start_status
from app.services.reason_codes import ReasonCode


class TestPhase2ReasonAndState(unittest.TestCase):
    def test_reason_mapping(self):
        self.assertEqual(_map_qa_error_to_reason("NO_RELIABLE_EVIDENCE"), ReasonCode.STRICT_MODE_BLOCKED.value)
        self.assertEqual(_map_qa_error_to_reason("MODEL_REQUEST_FAILED"), ReasonCode.MODEL_GENERATION_FAILED.value)
        self.assertEqual(_map_qa_error_to_reason("UNKNOWN_CODE"), ReasonCode.INTERNAL_ERROR.value)

    def test_index_state_machine_start_status(self):
        self.assertEqual(resolve_index_start_status("pending"), "parsing")
        self.assertEqual(resolve_index_start_status("failed"), "reindexing")
        self.assertEqual(resolve_index_start_status("indexed"), "reindexing")
        self.assertEqual(resolve_index_start_status("pending", force_reindex=True), "reindexing")


if __name__ == "__main__":
    unittest.main()

