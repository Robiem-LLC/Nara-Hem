import unittest

from keep_artifacts import artifacts, to_delete


def artifact(name, day, run=1, expired=False):
    """Returns an artifact as GitHub lists it."""
    return {
        "id": f"{name}@{day}",
        "name": name,
        "created_at": f"2026-11-{day:02d}T00:00:00Z",
        "expired": expired,
        "workflow_run": {"id": run},
    }


def ids(found):
    """Returns the IDs, to compare easily."""
    return [a["id"] for a in found]


class KeepArtifactsTests(unittest.TestCase):
    def test_eight_stored_keep_five_deletes_the_four_oldest_to_make_room(self):
        stored = [artifact("showcase-phones", day) for day in range(1, 9)]
        doomed = to_delete(stored, "showcase-phones", keep=5)
        self.assertEqual(ids(doomed), [f"showcase-phones@{day}" for day in range(1, 5)])

    def test_each_new_one_pushes_out_only_the_oldest(self):
        stored = [artifact("showcase-phones", day) for day in range(1, 6)]
        self.assertEqual(ids(to_delete(stored, "showcase-phones", keep=5)), ["showcase-phones@1"])
        self.assertEqual(to_delete(stored[:4], "showcase-phones", keep=5), [])

    def test_kinds_are_counted_separately_by_pattern(self):
        stored = [artifact(f"NaraHem-Android-{d}-abc", d) for d in range(1, 4)] + [
            artifact("showcase-site", d) for d in range(1, 4)
        ]
        self.assertEqual(
            ids(to_delete(stored, "NaraHem-Android-*", keep=2)),
            ["NaraHem-Android-1-abc@1", "NaraHem-Android-2-abc@2"],
        )

    def test_expired_and_current_run_files_are_left_alone(self):
        stored = [
            artifact("showcase-site", 1, expired=True),
            artifact("showcase-site", 2),
            artifact("showcase-site", 3, run=42),
        ]
        self.assertEqual(
            ids(to_delete(stored, "showcase-site", keep=1, current_run=42)), ["showcase-site@2"]
        )

    def test_every_page_is_listed(self):
        pages = {1: [artifact(str(i), 1) for i in range(100)], 2: [artifact("last", 2)]}

        def request(method, url, token):
            return {"artifacts": pages[int(url.rsplit("page=", 1)[1])]}

        self.assertEqual(len(artifacts("example/app", "t", request)), 101)


if __name__ == "__main__":
    unittest.main()
