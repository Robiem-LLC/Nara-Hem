import os
import tempfile
import unittest

from artifact_budget import MIB, artifacts, size_of, to_delete


def artifact(name, mib, day, run=1, expired=False):
    """Returns an artifact as GitHub lists it."""
    return {
        "id": name,
        "name": name,
        "size_in_bytes": int(mib * MIB),
        "created_at": f"2026-11-{day:02d}T00:00:00Z",
        "expired": expired,
        "workflow_run": {"id": run},
    }


class ArtifactBudgetTests(unittest.TestCase):
    def test_the_oldest_go_first_until_the_newest_fit(self):
        stored = [artifact("a", 100, 1), artifact("b", 100, 2), artifact("c", 100, 3)]
        self.assertEqual([a["id"] for a in to_delete(stored, 250 * MIB)], ["a"])
        self.assertEqual([a["id"] for a in to_delete(stored, 150 * MIB)], ["a", "b"])
        self.assertEqual(to_delete(stored, 300 * MIB), [])

    def test_once_one_is_deleted_everything_older_goes_too(self):
        stored = [artifact("small-old", 1, 1), artifact("big", 200, 2), artifact("new", 100, 3)]
        self.assertEqual([a["id"] for a in to_delete(stored, 150 * MIB)], ["small-old", "big"])

    def test_expired_and_current_run_files_are_left_alone(self):
        stored = [
            artifact("gone", 500, 1, expired=True),
            artifact("old", 100, 2),
            artifact("mine", 300, 3, run=42),
        ]
        self.assertEqual([a["id"] for a in to_delete(stored, 50 * MIB, current_run=42)], ["old"])

    def test_reserved_files_are_measured_folders_included(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "one.apk"), "wb") as f:
                f.write(b"x" * 1000)
            os.mkdir(os.path.join(folder, "media"))
            with open(os.path.join(folder, "media", "a.mp4"), "wb") as f:
                f.write(b"y" * 500)
            self.assertEqual(size_of([os.path.join(folder, "*.apk")]), 1000)
            self.assertEqual(size_of([os.path.join(folder, "media")]), 500)
            self.assertEqual(size_of([os.path.join(folder, "missing")]), 0)

    def test_every_page_is_listed(self):
        pages = {1: [artifact(str(i), 1, 1) for i in range(100)], 2: [artifact("last", 1, 2)]}

        def request(method, url, token):
            return {"artifacts": pages[int(url.rsplit("page=", 1)[1])]}

        self.assertEqual(len(artifacts("example/app", "t", request)), 101)


if __name__ == "__main__":
    unittest.main()
