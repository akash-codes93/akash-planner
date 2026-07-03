import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.db import local_store


class LocalStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._original_db_path = local_store.DB_PATH
        self._tmpdir = TemporaryDirectory()
        local_store.DB_PATH = Path(self._tmpdir.name) / "planner.sqlite3"
        local_store.init_db()

    def tearDown(self) -> None:
        local_store.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()


class SubtaskCascadeTest(LocalStoreTestCase):
    def _make_parent_with_subtasks(self, count: int) -> tuple[dict, list[dict]]:
        parent = local_store.create_task({"title": "Parent task"})
        subtasks = [
            local_store.create_task({"title": f"Subtask {i}", "parent_task_id": parent["id"]})
            for i in range(count)
        ]
        return parent, subtasks

    def test_parent_autocompletes_when_last_subtask_done(self) -> None:
        parent, subtasks = self._make_parent_with_subtasks(3)

        local_store.complete_task(subtasks[0]["id"])
        local_store.complete_task(subtasks[1]["id"])
        still_open = local_store.get_task(parent["id"])
        self.assertNotEqual(still_open["status"], "done")

        local_store.complete_task(subtasks[2]["id"])
        completed_parent = local_store.get_task(parent["id"])
        self.assertEqual(completed_parent["status"], "done")
        self.assertIsNotNone(completed_parent["completed_at"])

    def test_parent_stays_open_when_not_all_subtasks_done(self) -> None:
        parent, subtasks = self._make_parent_with_subtasks(2)

        local_store.complete_task(subtasks[0]["id"])
        parent_after = local_store.get_task(parent["id"])
        self.assertNotEqual(parent_after["status"], "done")

    def test_get_task_nests_subtasks(self) -> None:
        parent, subtasks = self._make_parent_with_subtasks(2)
        fetched = local_store.get_task(parent["id"])
        self.assertEqual(len(fetched["subtasks"]), 2)

    def test_list_tasks_excludes_subtasks_by_default(self) -> None:
        parent, _subtasks = self._make_parent_with_subtasks(2)
        top_level = local_store.list_tasks()
        top_level_ids = {task["id"] for task in top_level}
        self.assertIn(parent["id"], top_level_ids)
        for task in top_level:
            self.assertIsNone(task.get("parent_task_id"))

    def test_list_tasks_with_parent_filter_returns_children(self) -> None:
        parent, subtasks = self._make_parent_with_subtasks(2)
        children = local_store.list_tasks(parent_task_id=parent["id"])
        self.assertEqual({task["id"] for task in children}, {task["id"] for task in subtasks})


class TagModelTest(LocalStoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        local_store.clear_workspace()

    def test_get_or_create_tag_is_idempotent_case_insensitive(self) -> None:
        first = local_store.get_or_create_tag("Work")
        second = local_store.get_or_create_tag("work")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(local_store.list_tags()), 1)

    def test_create_task_attaches_tags_by_id_and_name(self) -> None:
        work = local_store.get_or_create_tag("Work")
        task = local_store.create_task(
            {"title": "Ship feature", "tag_ids": [work["id"]], "tag_names": ["Urgent"]}
        )
        tag_names = {tag["name"] for tag in task["tags"]}
        self.assertEqual(tag_names, {"Work", "Urgent"})
        self.assertEqual(task["status"], "backlog")

    def test_update_task_replaces_tag_set(self) -> None:
        task = local_store.create_task({"title": "Ship feature", "tag_names": ["Work"]})
        local_store.update_task(task["id"], {"tag_names": ["Personal"]})
        updated = local_store.get_task(task["id"])
        self.assertEqual({tag["name"] for tag in updated["tags"]}, {"Personal"})

    def test_list_tasks_filters_by_tag_including_parent_with_matching_own_tag(self) -> None:
        work = local_store.get_or_create_tag("Work")
        home = local_store.get_or_create_tag("Home")
        tagged = local_store.create_task({"title": "Tagged directly", "tag_ids": [work["id"]]})
        local_store.create_task({"title": "Untagged", "tag_ids": [home["id"]]})

        filtered = local_store.list_tasks(tag_id=work["id"])
        self.assertEqual([task["id"] for task in filtered], [tagged["id"]])

    def test_list_tasks_filters_include_subtask_tag_and_parent_not_orphaned(self) -> None:
        work = local_store.get_or_create_tag("Work")
        parent = local_store.create_task({"title": "Parent with no own tag"})
        subtask = local_store.create_task(
            {"title": "Subtask carries the tag", "parent_task_id": parent["id"], "tag_ids": [work["id"]]}
        )

        filtered = local_store.list_tasks(tag_id=work["id"])
        self.assertEqual([task["id"] for task in filtered], [parent["id"]])
        self.assertEqual(len(filtered[0]["subtasks"]), 1)
        self.assertEqual(filtered[0]["subtasks"][0]["id"], subtask["id"])


class ActivityStreakTest(LocalStoreTestCase):
    def _seed_counts(self, counts_by_offset: dict[int, int], today: date) -> None:
        with local_store._connect() as conn:
            for offset, count in counts_by_offset.items():
                day = (today - timedelta(days=offset)).isoformat()
                conn.execute(
                    "INSERT INTO activity_log (date, count, minutes) VALUES (?, ?, 0)",
                    (day, count),
                )

    def test_consecutive_days_streak(self) -> None:
        today = date.today()
        counts = {offset: 1 for offset in range(0, 5)}
        streak, freeze_available, newly_frozen = local_store._compute_streak(
            {(today - timedelta(days=o)).isoformat(): c for o, c in counts.items()},
            set(),
            today,
        )
        self.assertEqual(streak, 5)
        self.assertTrue(freeze_available)
        self.assertIsNone(newly_frozen)

    def test_single_gap_auto_freezes(self) -> None:
        today = date.today()
        # today active, yesterday (offset 1) empty, offsets 2-4 active
        counts = {0: 1, 2: 1, 3: 1, 4: 1}
        counts_map = {(today - timedelta(days=o)).isoformat(): c for o, c in counts.items()}
        streak, freeze_available, newly_frozen = local_store._compute_streak(counts_map, set(), today)
        # Gap at offset 1 is auto-frozen so the chain from today through offset 4 stays unbroken.
        self.assertEqual(streak, 4)
        self.assertEqual(newly_frozen, today - timedelta(days=1))
        self.assertFalse(freeze_available)

    def test_two_gaps_breaks_streak(self) -> None:
        today = date.today()
        # today active, offset1 empty (frozen), offset2 active, offset3 empty (second gap -> break)
        counts_map = {
            today.isoformat(): 1,
            (today - timedelta(days=2)).isoformat(): 1,
        }
        streak, freeze_available, newly_frozen = local_store._compute_streak(counts_map, set(), today)
        # Only the first gap (offset 1) gets frozen; offset 3 gap breaks the walk.
        self.assertEqual(streak, 2)
        self.assertEqual(newly_frozen, today - timedelta(days=1))

    def test_freeze_token_exhausted_within_seven_day_window(self) -> None:
        today = date.today()
        # A freeze was already used 3 days ago (within the trailing 7-day window).
        existing_freeze = {today - timedelta(days=3)}
        counts_map = {
            today.isoformat(): 1,
            (today - timedelta(days=3)).isoformat(): 1,
            (today - timedelta(days=4)).isoformat(): 1,
        }
        streak, freeze_available, newly_frozen = local_store._compute_streak(
            counts_map, existing_freeze, today
        )
        # Gap at offset 1 (yesterday) cannot be frozen again since a freeze was used
        # within the trailing 7-day window, so the streak breaks right away.
        self.assertEqual(streak, 1)
        self.assertIsNone(newly_frozen)
        self.assertFalse(freeze_available)

    def test_get_activity_returns_fixed_size_grid_with_streak(self) -> None:
        for _ in range(2):
            local_store.record_activity(minutes=10)
        result = local_store.get_activity(days=7)
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][-1]["count"], 2)
        self.assertGreaterEqual(result["streak"], 1)
        self.assertIn("freeze_available", result)


if __name__ == "__main__":
    unittest.main()
