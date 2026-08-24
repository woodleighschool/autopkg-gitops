from __future__ import annotations

import unittest

from common import ConfigError
from runtime import resource_patterns


class ResourcePatternTests(unittest.TestCase):
    def test_relative_pkgcreator_scripts_directory_is_a_recipe_resource(self) -> None:
        recipe = {
            "Input": {"SCRIPTS_DIR": "PackageScripts"},
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

    def test_pkgcreator_scripts_directory_cannot_escape_the_recipe(self) -> None:
        recipe = {
            "Process": [
                {
                    "Processor": "PkgCreator",
                    "Arguments": {
                        "pkg_request": {"scripts": "../SharedScripts"},
                    },
                }
            ],
        }

        with self.assertRaisesRegex(ConfigError, "escapes its directory"):
            resource_patterns(recipe, {})


if __name__ == "__main__":
    unittest.main()
