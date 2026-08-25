from __future__ import annotations

import unittest

from common import ConfigError
from runtime import resource_patterns


class ResourcePatternTests(unittest.TestCase):
    def test_cache_relative_pkgcreator_scripts_are_not_recipe_resources(self) -> None:
        recipe = {
            "Process": [
                {
                    "Processor": "PkgRootCreator",
                    "Arguments": {"pkgroot": "%RECIPE_CACHE_DIR%/Scripts"},
                },
                {
                    "Processor": "PkgCreator",
                    "Arguments": {
                        "pkg_request": {"scripts": "Scripts"},
                    },
                }
            ],
        }

        self.assertEqual(resource_patterns(recipe, {}), set())

    def test_explicit_recipe_directory_resource_is_included(self) -> None:
        recipe = {
            "Input": {"SCRIPTS_DIR": "%RECIPE_DIR%/PackageScripts"},
            "Process": [
                {
                    "Processor": "PkgCreator",
                    "Arguments": {
                        "pkg_request": {"scripts": "%SCRIPTS_DIR%"},
                    },
                }
            ],
        }

        self.assertEqual(resource_patterns(recipe, {}), {"PackageScripts"})

    def test_explicit_recipe_directory_resource_cannot_escape(self) -> None:
        recipe = {
            "Process": [
                {
                    "Processor": "PkgCreator",
                    "Arguments": {
                        "pkg_request": {"scripts": "%RECIPE_DIR%/../SharedScripts"},
                    },
                }
            ],
        }

        with self.assertRaisesRegex(ConfigError, "escapes its directory"):
            resource_patterns(recipe, {})


if __name__ == "__main__":
    unittest.main()
