import unittest

from app.discovery.classification import ClassificationEngine
from app.discovery.models import (
    Application,
    CLASS_DRIVER,
    CLASS_FRAMEWORK,
    CLASS_LANGUAGE_PACK,
    CLASS_NORMAL,
    CLASS_RUNTIME,
    CLASS_SYSTEM,
    CLASS_UPDATE,
)


def app(name, **extra):
    a = Application(id=name, name=name)
    a.extra.update(extra)
    return a


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = ClassificationEngine()

    def test_normal_application(self):
        self.assertEqual(
            self.engine.classify(app("Google Chrome", flags={})),
            CLASS_NORMAL,
        )

    def test_update_by_system_component(self):
        self.assertEqual(
            self.engine.classify(app("Microsoft Edge Update",
                                      flags={"SystemComponent": True})),
            CLASS_UPDATE,
        )

    def test_update_by_kb_number(self):
        self.assertEqual(self.engine.classify(app("Security Update for Windows (KB5034123)",
                                                   flags={})), CLASS_UPDATE)

    def test_runtime(self):
        self.assertEqual(
            self.engine.classify(app("Microsoft Visual C++ 2015 Redistributable",
                                     flags={})),
            CLASS_RUNTIME,
        )

    def test_framework(self):
        self.assertEqual(
            self.engine.classify(app("Microsoft .NET Framework 4.8", flags={})),
            CLASS_FRAMEWORK,
        )

    def test_language_pack(self):
        self.assertEqual(
            self.engine.classify(app("German Language Pack", flags={})),
            CLASS_LANGUAGE_PACK,
        )

    def test_driver(self):
        self.assertEqual(
            self.engine.classify(app("Realtek Audio Driver", flags={})),
            CLASS_DRIVER,
        )

    def test_system_resource_package(self):
        self.assertEqual(
            self.engine.classify(app("Something", package_type="resource")),
            CLASS_SYSTEM,
        )

    def test_non_surface_class_hidden(self):
        a = app("Microsoft Edge Update", flags={"SystemComponent": True})
        self.engine.classify(a)
        self.assertFalse(a.surfaceable)


if __name__ == "__main__":
    unittest.main()
