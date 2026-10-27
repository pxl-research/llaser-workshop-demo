import sys
import unittest
from pathlib import Path

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.Chunking.Splitter import MarkdownSplitter

MAX = 2000


def squash(text: str) -> str:
    return "".join(text.split())


class MarkdownSplitterMaxChunkSizeTests(unittest.TestCase):
    def setUp(self):
        self.splitter = MarkdownSplitter(max_chunk_size=MAX)

    def assert_bounded_and_preserved(self, text: str) -> list[str]:
        chunks = self.splitter.split([text])
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), MAX)
        self.assertEqual(squash("".join(chunks)), squash(text))
        return chunks

    def test_short_text_stays_a_single_chunk(self):
        text = "# Title\n\nA short paragraph. Nothing to split."
        self.assertEqual(self.splitter.split([text]), [text])

    def test_headings_still_split_sections(self):
        text = "# One\nfirst body\n\n## Two\nsecond body"
        self.assertEqual(
            self.splitter.split([text]),
            ["# One\nfirst body", "## Two\nsecond body"],
        )

    def test_long_punctuated_paragraph(self):
        text = " ".join(f"Sentence number {i} is a plain short sentence." for i in range(300))
        self.assertGreater(len(text), MAX * 3)
        self.assert_bounded_and_preserved(text)

    def test_long_run_without_punctuation_but_with_spaces(self):
        text = " ".join(f"word{i}" for i in range(1000))[:6000]
        self.assertEqual(len(text), 6000)
        self.assert_bounded_and_preserved(text)

    def test_long_markdown_table_splits_on_newlines(self):
        row = "| cell alpha | cell beta | cell gamma | 12345 |"
        text = "\n".join(row for _ in range(200))[:6000]
        self.assertEqual(len(text), 6000)
        chunks = self.assert_bounded_and_preserved(text)
        # newline fallback keeps whole rows together wherever a row fits
        self.assertTrue(all(chunk.startswith("|") for chunk in chunks))

    def test_single_token_without_whitespace_is_hard_cut(self):
        text = "x" * 5000
        chunks = self.assert_bounded_and_preserved(text)
        self.assertEqual("".join(chunks), text)

    def test_long_token_between_normal_words_keeps_order(self):
        text = "head words " + "y" * 4500 + " tail words"
        chunks = self.assert_bounded_and_preserved(text)
        self.assertEqual(squash("".join(chunks)), squash(text))
        self.assertTrue(chunks[0].startswith("head words"))
        self.assertTrue(chunks[-1].endswith("tail words"))

    def test_heading_section_over_limit_is_bounded(self):
        body = "no punctuation here " * 400
        text = f"# Heading\n{body}\n## Next\nshort"
        chunks = self.splitter.split([text])
        for chunk in chunks:
            self.assertLessEqual(len(chunk), MAX)
        # the heading is repeated on every sub-split piece
        self.assertEqual(squash("".join(chunks).replace("# Heading", "")), squash(text.replace("# Heading", "")))
        self.assertEqual(chunks[-1], "## Next\nshort")

    def test_sub_split_chunks_keep_section_heading(self):
        body = "Plain sentence about the topic. " * 160
        chunks = self.splitter.split([f"## Section\n{body}"])
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(chunk.startswith("## Section\n"))
            self.assertLessEqual(len(chunk), MAX)


if __name__ == "__main__":
    unittest.main()
