import unittest

from app.services.qa_service import _pack_context_and_references


class _Chunk:
    def __init__(self, cid: int, file_id: int, idx: int, content: str):
        self.id = cid
        self.file_id = file_id
        self.chunk_index = idx
        self.content = content
        self.section_title = None
        self.page_number = None


class TestQAContextAssembly(unittest.TestCase):
    def test_adjacent_redundancy_is_deduped(self):
        items = [
            {"chunk": _Chunk(1, 1, 10, "alpha beta gamma"), "file_name": "doc1", "score": 0.9},
            {"chunk": _Chunk(2, 1, 11, "alpha beta gamma"), "file_name": "doc1", "score": 0.89},
            {"chunk": _Chunk(3, 2, 1, "delta epsilon"), "file_name": "doc2", "score": 0.8},
        ]
        blocks, refs, used, _, packed_n, _ = _pack_context_and_references(
            items,
            seed_chunk_ids={1, 2, 3},
            max_context_chars=5000,
            dedupe_adjacent_chunks=True,
        )
        self.assertTrue(packed_n <= 2)
        self.assertTrue(len(used) >= 1)
        self.assertEqual(len(blocks), len(refs))


if __name__ == "__main__":
    unittest.main()
