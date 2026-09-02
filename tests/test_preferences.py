import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from preferences import write_preferences


class PreferencesTests(unittest.TestCase):
    def test_recipe_repo_dir_matches_materialized_repositories(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo_root = root / "custom-repositories"
            repository = repo_root / "com.github.example.recipes"
            repository.mkdir(parents=True)
            overrides = root / "overrides"
            overrides.mkdir()
            manifest = root / "repositories.json"
            manifest.write_text(json.dumps({
                "version": 1,
                "repositories": [{
                    "url": "https://github.com/example/recipes",
                    "ref": "main",
                    "revision": "a" * 40,
                }],
            }))

            state = root / "state"
            write_preferences(state, repo_root, overrides, root / "recipes", manifest)
            with (state / "preferences.plist").open("rb") as source:
                preferences = plistlib.load(source)

            self.assertEqual(preferences["RECIPE_REPO_DIR"], str(repo_root))
            self.assertEqual(preferences["RECIPE_SEARCH_DIRS"], [str(repository)])
            self.assertEqual(list(preferences["RECIPE_REPOS"]), [str(repository)])
