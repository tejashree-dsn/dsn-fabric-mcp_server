import tempfile
import unittest
from pathlib import Path

from result_store import ResultStore


class ResultStoreTests(unittest.TestCase):
    def test_write_page_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ResultStore(Path(tmp), ttl_hours=24)
            qid = store.create_query({"report": "test"})
            store.begin_dataset(qid, "data", template_name="x.sql", query_hash="abc")
            store.append_rows(qid, "data", [[1, "a"], [2, "b"], [3, "c"]])
            store.finalize_dataset(
                qid,
                "data",
                columns=["id", "name"],
                row_count=3,
                truncated=False,
            )
            page = store.get_page(qid, "data", offset=1, limit=1)
            self.assertEqual(page["rows"], [[2, "b"]])
            self.assertTrue(page["has_more"])
            meta = store.get_metadata(qid)
            self.assertEqual(meta["datasets"]["data"]["row_count"], 3)


if __name__ == "__main__":
    unittest.main()
