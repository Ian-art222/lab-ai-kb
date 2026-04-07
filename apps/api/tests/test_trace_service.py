import unittest

from app.services.trace_service import list_traces


class _FakeQuery:
    def __init__(self):
        self.filters = 0
        self._limit = 0

    def filter(self, *args, **kwargs):
        self.filters += 1
        return self

    def count(self):
        return 3

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def all(self):
        return []


class _FakeDB:
    def __init__(self):
        self.q = _FakeQuery()

    def query(self, *args, **kwargs):
        return self.q


class TestTraceService(unittest.TestCase):
    def test_list_traces_filters_and_limit(self):
        db = _FakeDB()
        total, rows = list_traces(
            db,
            trace_id="t1",
            request_id="r1",
            session_id=1,
            abstained=True,
            failed=True,
            limit=500,
        )
        self.assertEqual(total, 3)
        self.assertEqual(rows, [])
        self.assertEqual(db.q._limit, 200)
        self.assertGreaterEqual(db.q.filters, 5)


if __name__ == "__main__":
    unittest.main()

