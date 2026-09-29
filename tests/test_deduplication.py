import sys
import unittest

from app.discovery.deduplication import (
    DeduplicationEngine,
    name_similarity,
    score_pair,
    versions_compatible,
)
from app.discovery.models import (
    Component,
    RawDiscoveryItem,
    SOURCE_REGISTRY,
    SOURCE_SERVICE,
)
from app.discovery.normalizer import Normalizer


def item(name, source=SOURCE_REGISTRY, **kwargs):
    base = dict(id=name, name=name, source=source, installer_type="exe")
    base.update(kwargs)
    return RawDiscoveryItem(**base)


def normalize(*items):
    return Normalizer().normalize_all(list(items))


class NameSimilarityTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(name_similarity("google chrome", "google chrome"), 1.0)

    def test_vendor_only_overlap_is_low(self):
        # Same vendor, different products: must NOT be considered similar.
        self.assertLess(name_similarity("google chrome", "google drive"), 0.5)

    def test_subset_is_strong(self):
        self.assertGreaterEqual(name_similarity("chrome", "google chrome"), 0.85)


class VersionCompatibilityTests(unittest.TestCase):
    def test_both_empty_no_signal(self):
        self.assertFalse(versions_compatible("", ""))

    def test_equal(self):
        self.assertTrue(versions_compatible("1.0", "1.0"))

    def test_different(self):
        self.assertFalse(versions_compatible("1.0", "2.0"))


class ScoreTests(unittest.TestCase):
    def test_product_code_dominates(self):
        a, b = normalize(
            item("App", product_code="{AAAAAAAA-1111-2222-3333-444444444444}"),
            item("App", product_code="{AAAAAAAA-1111-2222-3333-444444444444}"),
        )
        self.assertGreaterEqual(score_pair(a, b), 100)

    def test_same_vendor_different_app_not_merged(self):
        a, b = normalize(
            item("Google Chrome", publisher="Google LLC"),
            item("Google Drive", publisher="Google LLC"),
        )
        self.assertLess(score_pair(a, b), 60)

    def test_identical_exe_merges(self):
        exe = sys.executable
        a, b = normalize(
            item("Foo", executable_path=exe),
            item("Foo Service", source=SOURCE_SERVICE, executable_path=exe),
        )
        self.assertGreaterEqual(score_pair(a, b), 70)


class DedupTests(unittest.TestCase):
    def test_merge_by_product_code(self):
        engine = DeduplicationEngine()
        items = normalize(
            item("App", product_code="{AAAAAAAA-1111-2222-3333-444444444444}"),
            item("App", product_code="{AAAAAAAA-1111-2222-3333-444444444444}"),
        )
        apps = engine.deduplicate(items)
        self.assertEqual(len(apps), 1)

    def test_no_merge_different_apps_same_vendor(self):
        engine = DeduplicationEngine()
        items = normalize(
            item("Google Chrome", publisher="Google LLC", version="1.0"),
            item("Google Drive", publisher="Google LLC", version="2.0"),
        )
        apps = engine.deduplicate(items)
        self.assertEqual(len(apps), 2)

    def test_components_and_sources_merged(self):
        exe = sys.executable
        service_item = item(
            "Foo Service", source=SOURCE_SERVICE, executable_path=exe,
            components=[Component(kind="service", name="Foo Service", path=exe)],
        )
        reg_item = item(
            "Foo", source=SOURCE_REGISTRY, executable_path=exe,
            components=[Component(kind="executable", name="Foo", path=exe)],
        )
        apps = DeduplicationEngine().deduplicate(normalize(reg_item, service_item))
        self.assertEqual(len(apps), 1)
        app = apps[0]
        self.assertIn(SOURCE_REGISTRY, app.sources)
        self.assertIn(SOURCE_SERVICE, app.sources)
        kinds = {c.kind for c in app.components}
        self.assertIn("service", kinds)
        self.assertIn("executable", kinds)


if __name__ == "__main__":
    unittest.main()
