import json
import tempfile
import unittest
from pathlib import Path

from scripts import discover_catalog as collector


class CollectorTests(unittest.TestCase):
    def test_price_and_product_id_parsing(self):
        self.assertEqual(collector.parse_number("1.999,90"), 1999.90)
        self.assertEqual(collector.parse_number("1,999.90"), 1999.90)
        self.assertEqual(collector.extract_model_id("https://www.decathlon.de/c443m8807204"), "8807204")
        self.assertEqual(collector.extract_model_id("https://www.decathlon.de/p/test/_/R-p-8612279"), "8612279")
        self.assertEqual(collector.extract_model_id("https://www.decathlon.at/search?mc=8383182"), "8383182")

    def test_product_page_parser_prefers_jsonld(self):
        page = """
        <h1>Quechua tent</h1>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Quechua MH100 tent","category":"Camping","offers":{"price":"44.99","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}
        </script>
        """
        store = next(item for item in collector.DEFAULT_STORES if item["code"] == "de")
        parsed = collector.parse_product(page, "https://www.decathlon.de/p/quechua/_/R-p-8612279", store, "8612279")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "8612279")
        self.assertEqual(parsed["name"], "Quechua MH100 tent")
        self.assertEqual(parsed["price"], 44.99)
        self.assertEqual(parsed["currency"], "EUR")
        self.assertTrue(parsed["stock"])

    def test_sitemap_product_url_extraction(self):
        sitemap = """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://www.decathlon.de/p/one/_/R-p-8612279</loc></url>
          <url><loc>https://www.decathlon.de/c/sport</loc></url>
        </urlset>
        """
        locs = collector.sitemap_locs(sitemap)
        self.assertEqual(len(locs), 2)
        self.assertTrue(collector.is_product_url(locs[0]))
        self.assertFalse(collector.is_product_url(locs[1]))

    def test_delta_only_marks_vanished_after_complete_store_scan(self):
        previous = {
            "products": [{"id": "1234567", "prices": {"de": {"price": 10, "currency": "EUR", "eur": 10, "stock": True}}}],
            "stores": [{"code": "de", "scan_complete": True}],
        }
        current_partial = {
            "generated_at": "2026-10-09T00:00:00Z",
            "products": [],
            "stores": [{"code": "de", "scan_complete": False}],
        }
        self.assertEqual(collector.build_delta(previous, current_partial)["products"]["vanished"], [])

        current_complete = {
            "generated_at": "2026-10-09T00:00:00Z",
            "products": [],
            "stores": [{"code": "de", "scan_complete": True}],
        }
        delta = collector.build_delta(previous, current_complete)
        self.assertEqual(delta["products"]["vanished"], ["1234567"])

    def test_history_file_is_updated_per_product(self):
        previous = {"products": [], "stores": []}
        current = {
            "generated_at": "2026-10-09T00:00:00Z",
            "products": [{"id": "1234567", "name": "Test item", "prices": {"de": {"price": 10, "currency": "EUR", "eur": 10, "stock": True}}}],
            "stores": [{"code": "de", "scan_complete": True}],
        }
        delta = collector.build_delta(previous, current)
        with tempfile.TemporaryDirectory() as directory:
            collector.update_histories(Path(directory), previous, current, delta)
            history = json.loads((Path(directory) / "1234567.json").read_text(encoding="utf-8"))
        self.assertEqual(history["product_id"], "1234567")
        self.assertEqual(history["status"], "active")
        self.assertEqual(history["events"][0]["type"], "product_discovered")
        self.assertEqual(len(history["snapshots"]), 1)

    def test_partial_scan_keeps_other_markets(self):
        offer = {"price": 1, "currency": "EUR", "eur": 1, "stock": True}
        previous = {
            "stores": [{"code": "de", "scan_complete": True}, {"code": "fr", "scan_complete": True}],
            "products": [{"id": "1", "name": "Tent", "prices": {"de": offer, "fr": offer}}, {"id": "2", "name": "Bag", "prices": {"fr": offer}}],
        }
        current = {
            "stores": [{"code": "de", "scan_complete": True}],
            "products": [{"id": "1", "name": "Tent", "prices": {"de": {**offer, "price": 2}}}],
        }
        merged = collector.merge_partial_scan(previous, current, {"de"})
        self.assertEqual([s["code"] for s in merged["stores"]], ["de", "fr"])
        by_id = {p["id"]: p for p in merged["products"]}
        self.assertEqual(by_id["1"]["prices"]["de"]["price"], 2)
        self.assertIn("fr", by_id["1"]["prices"])
        self.assertIn("2", by_id)

    def test_progress_logs_finished_stores_without_tty(self):
        import io
        stream = io.StringIO()
        progress = collector.Progress(2, stream)
        progress.store_started("de", 1)
        progress.product_done("de")
        progress.store_finished("de", 1, True)
        self.assertIn("[1/2] de: 1 products · complete", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
