"""Stub configurations module for pytest-django compatibility."""

import sys


# Stub implementations for when django-configurations is not installed
class DummySettings:
    pass


class ImporterModule:
    classysettings = DummySettings()

    @staticmethod
    def install():
        """Dummy install method."""
        pass


# Create a mock importer
importer = ImporterModule()

# Register all modules in sys.modules
this_module = sys.modules[__name__]
sys.modules["configurations"] = this_module
sys.modules["configurations.importer"] = importer
sys.modules["classysettings"] = importer.classysettings
