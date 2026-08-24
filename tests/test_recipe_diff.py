from __future__ import annotations

import unittest

from recipe_diff import recipe_section


class RecipeSectionTests(unittest.TestCase):
    def test_recipe_content_is_rendered_as_a_diff(self) -> None:
        section = recipe_section(
            "local.munki.Example",
            "Description: old\n",
            "Description: new\n",
            [
                {
                    "recipe": "local.munki.Example",
                    "path": "Example/Example.recipe.yaml",
                    "url": "https://example.invalid/recipe",
                }
            ],
            [],
            [],
            None,
        )

        self.assertIsNotNone(section)
        assert section is not None
        self.assertIn("```diff", section)
        self.assertIn("-Description: old", section)
        self.assertIn("+Description: new", section)
        self.assertNotIn("Changed upstream files:", section)

    def test_non_recipe_changes_are_compact_source_links(self) -> None:
        section = recipe_section(
            "local.munki.Example",
            "Description: unchanged\n",
            "Description: unchanged\n",
            [],
            [
                {
                    "recipe": "local.munki.Example",
                    "processor": "example/Processor",
                    "path": "Processors/Processor.py",
                    "url": "https://example.invalid/processor",
                }
            ],
            [
                {
                    "recipe": "local.munki.Example",
                    "path": "Example/Scripts/install.sh",
                    "url": "https://example.invalid/resource",
                }
            ],
            None,
        )

        self.assertIsNotNone(section)
        assert section is not None
        self.assertNotIn("```diff", section)
        self.assertIn("Changed upstream files:", section)
        self.assertIn(
            "Processor [`example/Processor`](https://example.invalid/processor)",
            section,
        )
        self.assertIn(
            "Imported resource [`Example/Scripts/install.sh`](https://example.invalid/resource)",
            section,
        )

    def test_recipe_without_a_rendered_change_links_its_source_diff(self) -> None:
        section = recipe_section(
            "local.munki.Example",
            "Description: unchanged\n",
            "Description: unchanged\n",
            [
                {
                    "recipe": "local.munki.Example",
                    "path": "Example/Example.recipe.yaml",
                    "url": "https://example.invalid/recipe",
                }
            ],
            [],
            [],
            None,
        )

        self.assertIsNotNone(section)
        assert section is not None
        self.assertNotIn("```diff", section)
        self.assertIn(
            "Recipe [`Example/Example.recipe.yaml`](https://example.invalid/recipe)",
            section,
        )


if __name__ == "__main__":
    unittest.main()
