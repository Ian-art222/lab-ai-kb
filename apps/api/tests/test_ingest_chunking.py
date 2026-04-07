import unittest

from app.services.ingest_service import _chunk_text, _limit_segments, _split_markdown_sections


class TestIngestChunking(unittest.TestCase):
    def test_markdown_sections_keep_headings(self):
        md = "# 标题A\n\n第一段\n\n## 小节\n\n```python\nprint('x')\n```"
        sections = _split_markdown_sections(md)
        self.assertGreaterEqual(len(sections), 2)
        self.assertTrue(any(s.get("section_title") == "标题A" for s in sections))

    def test_chunk_text_preserves_section_title(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks, warning = _chunk_text(
            text,
            page_number=1,
            section_title="实验方法",
            block_type="paragraph",
        )
        self.assertTrue(chunks)
        self.assertTrue(warning is None or isinstance(warning, str))
        self.assertTrue(all(c.get("section_title") == "实验方法" for c in chunks))

    def test_limit_segments_preserves_metadata(self):
        segments = [
            {
                "text": "A" * 100,
                "page_number": 3,
                "section_title": "章节一",
                "block_type": "table",
                "heading_level": 2,
            }
        ]
        limited, truncated = _limit_segments(segments)
        self.assertFalse(truncated)
        self.assertEqual(limited[0]["page_number"], 3)
        self.assertEqual(limited[0]["section_title"], "章节一")
        self.assertEqual(limited[0]["block_type"], "table")


if __name__ == "__main__":
    unittest.main()
