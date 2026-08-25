from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import upstreams


class ReviewClassificationTests(unittest.TestCase):
    identifier = "local.munki.Example"
    repository_name = "example"
    recipe_path = "Example/Example.download.recipe.yaml"
    processor_path = "Processors/ExampleProcessor.py"
    resource_path = "Example/Scripts/install.sh"

    def classify(
        self, changed_path: str
    ) -> tuple[
        list[str],
        list[dict[str, str]],
        list[dict[str, str]],
        list[dict[str, str]],
    ]:
        previous_repository = {
            "name": self.repository_name,
            "url": "https://github.com/example/recipes.git",
            "ref": "main",
            "revision": "previous",
        }
        current_repository = {**previous_repository, "revision": "current"}
        previous_manifest = {"repositories": [previous_repository]}
        current_manifest = {"repositories": [current_repository]}
        override = {"Identifier": self.identifier, "Input": {}}
        overrides = {self.identifier: (Path("RecipeOverrides/Example.recipe.yaml"), override)}
        recipe_references = {
            self.identifier: {self.repository_name: {self.recipe_path}}
        }
        processors = {
            self.identifier: {
                self.repository_name: {
                    self.processor_path: {"example/ExampleProcessor"}
                }
            }
        }

        with (
            patch.object(upstreams, "manifest_at", return_value=previous_manifest),
            patch.object(upstreams, "load_manifest", return_value=current_manifest),
            patch.object(upstreams, "overrides_at", return_value=overrides),
            patch.object(upstreams, "load_overrides", return_value=overrides),
            patch.object(
                upstreams,
                "parent_recipe_references_by_recipe",
                return_value=recipe_references,
            ),
            patch.object(
                upstreams,
                "processor_references_by_recipe",
                return_value=processors,
            ),
            patch.object(upstreams, "changed_paths", return_value={changed_path}),
            patch.object(upstreams, "ensure_checkout", return_value=Path("checkout")),
            patch.object(
                upstreams,
                "recipe_resources",
                return_value={self.resource_path},
            ),
        ):
            (
                recipes,
                _,
                _,
                changed_recipe_files,
                changed_processors,
                changed_resources,
                _,
                _,
            ) = upstreams.affected_recipes(
                "base",
                Path("repositories.json"),
                Path("repos"),
                {},
                [],
            )
        return recipes, changed_recipe_files, changed_processors, changed_resources

    def test_recipe_change_requires_review(self) -> None:
        recipes, recipe_files, processors, resources = self.classify(self.recipe_path)

        self.assertEqual(recipes, [self.identifier])
        self.assertEqual([item["path"] for item in recipe_files], [self.recipe_path])
        self.assertEqual(processors, [])
        self.assertEqual(resources, [])

    def test_used_processor_change_requires_review_with_source_link(self) -> None:
        recipes, recipe_files, processors, resources = self.classify(self.processor_path)

        self.assertEqual(recipes, [self.identifier])
        self.assertEqual(recipe_files, [])
        self.assertEqual(
            [(item["processor"], item["path"]) for item in processors],
            [("example/ExampleProcessor", self.processor_path)],
        )
        self.assertEqual(resources, [])

    def test_imported_resource_change_requires_review_with_source_link(self) -> None:
        recipes, recipe_files, processors, resources = self.classify(self.resource_path)

        self.assertEqual(recipes, [self.identifier])
        self.assertEqual(recipe_files, [])
        self.assertEqual(processors, [])
        self.assertEqual(
            [item["path"] for item in resources],
            [self.resource_path],
        )

    def test_unrelated_upstream_change_does_not_require_review(self) -> None:
        recipes, recipe_files, processors, resources = self.classify("README.md")

        self.assertEqual(recipes, [])
        self.assertEqual(recipe_files, [])
        self.assertEqual(processors, [])
        self.assertEqual(resources, [])


class RecipeResourceTests(unittest.TestCase):
    def test_trusted_pkgcreator_script_is_an_imported_resource(self) -> None:
        repository = {
            "name": "example",
            "url": "https://github.com/example/recipes.git",
            "ref": "main",
            "revision": "current",
        }
        override = {
            "Input": {},
            "ParentRecipeTrustInfo": {
                "parent_recipes": {},
                "scripts": {
                    "Scripts/postinstall": {
                        "path": "~/Library/AutoPkg/RecipeRepos/example/Example/Scripts/postinstall"
                    }
                },
            },
        }

        resources = upstreams.recipe_resources(
            override,
            "example",
            repository,
            [repository],
            Path("checkout"),
        )

        self.assertEqual(resources, {"Example/Scripts/postinstall"})


class GitHubOutputTests(unittest.TestCase):
    def test_review_required_is_the_authoritative_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                upstreams.write_github_output(
                    ["local.munki.Example"],
                    ["local.munki.Example"],
                    ["local.munki.Example"],
                    [],
                    [],
                    [],
                    {},
                    [],
                )

            content = output.read_text(encoding="utf-8")

        self.assertIn("review_required=true\n", content)
        self.assertNotIn("changed=", content)
        self.assertNotIn("repositories=", content)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/upstreams.yaml"
        ).read_text(encoding="utf-8")
        self.workflow = workflow
        self.automerge = workflow.split("\n  automerge:\n", 1)[1]

    def test_automerge_consumes_review_classification_directly(self) -> None:
        self.assertIn(
            "needs.filter.outputs.review_required != 'true'",
            self.automerge,
        )
        self.assertNotIn("Check generated override changes", self.automerge)
        self.assertNotIn("RecipeOverrides", self.automerge)
        self.assertIn('--match-head-commit "$HEAD_SHA"', self.automerge)

    def test_review_required_head_disables_existing_automerge_before_locking(self) -> None:
        freeze = self.workflow.split("\n  freeze:\n", 1)[1].split("\n  lock:\n", 1)[0]
        lock = self.workflow.split("\n  lock:\n", 1)[1].split(
            "\n  publish-lock:\n", 1
        )[0]

        self.assertIn("needs.filter.outputs.review_required == 'true'", freeze)
        self.assertIn("gh pr merge", freeze)
        self.assertIn("--disable-auto", freeze)
        self.assertIn("needs.freeze.result == 'success'", lock)


class AutoPkgWorkflowContractTests(unittest.TestCase):
    def test_summary_upload_requires_an_attempted_autopkg_run(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/autopkg.yml"
        ).read_text(encoding="utf-8")
        run_step = workflow.split("      - name: Run AutoPkg\n", 1)[1].split(
            "      - name: Upload run summary\n", 1
        )[0]
        upload_step = workflow.split("      - name: Upload run summary\n", 1)[1]

        self.assertIn("        id: autopkg\n", run_step)
        self.assertIn("steps.autopkg.outcome == 'success'", upload_step)
        self.assertIn("steps.autopkg.outcome == 'failure'", upload_step)
        self.assertIn("if-no-files-found: error", upload_step)


if __name__ == "__main__":
    unittest.main()
