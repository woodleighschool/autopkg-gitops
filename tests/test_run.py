from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run as autopkg_run


class SensitiveStateTests(unittest.TestCase):
    def test_cleanup_removes_raw_results_and_managed_receipts_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "state"
            cache_dir = root / "cache"
            managed_cache = cache_dir / "local.munki.Managed"
            unmanaged_cache = cache_dir / "local.munki.Unmanaged"

            (managed_cache / "receipts").mkdir(parents=True)
            (managed_cache / "receipts" / "run.plist").write_text("secret")
            (managed_cache / "downloads").mkdir()
            (managed_cache / "downloads" / "installer.pkg").write_text("cached")
            (unmanaged_cache / "receipts").mkdir(parents=True)
            (unmanaged_cache / "receipts" / "run.plist").write_text("other")
            state_dir.mkdir()
            (state_dir / "autopkg-results.plist").write_text("secret")
            (cache_dir / "autopkg_results.plist").write_text("secret")

            autopkg_run.SensitiveState(
                state_dir=state_dir,
                cache_dir=cache_dir,
                recipe_identifiers={"local.munki.Managed"},
            ).clean()

            self.assertFalse((managed_cache / "receipts").exists())
            self.assertFalse((state_dir / "autopkg-results.plist").exists())
            self.assertFalse((cache_dir / "autopkg_results.plist").exists())
            self.assertEqual(
                (managed_cache / "downloads" / "installer.pkg").read_text(),
                "cached",
            )
            self.assertEqual(
                (unmanaged_cache / "receipts" / "run.plist").read_text(),
                "other",
            )

    def test_cleanup_refuses_to_traverse_a_linked_recipe_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "state"
            cache_dir = root / "cache"
            external_receipts = root / "external" / "receipts"
            external_receipts.mkdir(parents=True)
            (external_receipts / "run.plist").write_text("keep")
            cache_dir.mkdir()
            (cache_dir / "local.munki.Managed").symlink_to(external_receipts.parent)

            with self.assertRaises(autopkg_run.CleanupError):
                autopkg_run.SensitiveState(
                    state_dir=state_dir,
                    cache_dir=cache_dir,
                    recipe_identifiers={"local.munki.Managed"},
                ).clean()

            self.assertEqual((external_receipts / "run.plist").read_text(), "keep")


class RunTests(unittest.TestCase):
    def test_raw_state_is_cleaned_before_and_after_every_run(self) -> None:
        for return_code in (0, 7):
            with self.subTest(return_code=return_code):
                self.assert_run_cleans_raw_state(return_code)

    def assert_run_cleans_raw_state(self, return_code: int) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "state"
            cache_dir = root / "cache"
            output_dir = root / "artifacts"
            receipt_dir = cache_dir / "local.munki.Managed" / "receipts"
            state_dir.mkdir()
            cache_dir.mkdir()
            (state_dir / "selection.json").write_text(
                '{"recipes":["local.munki.Managed"]}'
            )
            (state_dir / "autopkg-results.plist").write_text("stale")
            (cache_dir / "autopkg_results.plist").write_text("stale")
            receipt_dir.mkdir(parents=True)
            (receipt_dir / "stale.plist").write_text("stale")

            def fake_autopkg(
                command: list[str], check: bool
            ) -> subprocess.CompletedProcess[str]:
                self.assertFalse((state_dir / "autopkg-results.plist").exists())
                self.assertFalse((cache_dir / "autopkg_results.plist").exists())
                self.assertFalse(receipt_dir.exists())
                (state_dir / "autopkg-results.plist").write_text("current")
                (cache_dir / "autopkg_results.plist").write_text("current")
                receipt_dir.mkdir(parents=True)
                (receipt_dir / "current.plist").write_text("current")
                return subprocess.CompletedProcess(command, return_code)

            def fake_report(*, state_dir: Path, exit_code: int, output_dir: Path) -> None:
                self.assertEqual(exit_code, return_code)
                self.assertTrue((state_dir / "autopkg-results.plist").exists())
                self.assertEqual(output_dir, root / "artifacts")

            with (
                patch.object(
                    autopkg_run,
                    "load_overrides",
                    return_value={"local.munki.Managed": (Path("override"), {})},
                ),
                patch.object(autopkg_run.subprocess, "run", side_effect=fake_autopkg),
                patch.object(autopkg_run, "write_report", side_effect=fake_report),
            ):
                exit_code = autopkg_run.run(
                    state_dir=state_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                )

            self.assertEqual(exit_code, return_code)
            self.assertFalse((state_dir / "autopkg-results.plist").exists())
            self.assertFalse((cache_dir / "autopkg_results.plist").exists())
            self.assertFalse(receipt_dir.exists())


if __name__ == "__main__":
    unittest.main()
