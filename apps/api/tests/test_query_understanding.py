import unittest

from app.services.qa_agent_workflow import route_task_scope_skill
from app.services.query_understanding import (
    QUERY_TYPE_PROCEDURE,
    build_query_analysis,
    compact_query_trace_for_meta,
)


class TestQueryUnderstanding(unittest.TestCase):
    def test_procedure_rewrite_and_retrieval_queries(self):
        q = "请问如何配置数据库连接池的超时参数？"
        routing = route_task_scope_skill(question=q, scope_type="all", file_ids=None)
        nq = " ".join(q.split())
        a = build_query_analysis(q, routing=routing, normalized_query=nq, base_variants=[nq])
        self.assertEqual(a["query_type"], QUERY_TYPE_PROCEDURE)
        self.assertTrue(a["retrieval_queries"])
        self.assertIn("stripped_filler", a.get("analysis_notes", []))
        c = compact_query_trace_for_meta(a)
        self.assertIn("query_type", c)
        self.assertGreaterEqual(c.get("retrieval_query_count", 0), 1)


if __name__ == "__main__":
    unittest.main()
