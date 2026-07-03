import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.db import local_store


class AiPlannerTitleCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_db_path = local_store.DB_PATH
        self._tmpdir = TemporaryDirectory()
        local_store.DB_PATH = Path(self._tmpdir.name) / "planner.sqlite3"
        local_store.init_db()

    def tearDown(self) -> None:
        local_store.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def test_command_wrapper_is_removed_from_task_title(self) -> None:
        command = (
            "Create a backlog task in goals. Basically, it is watching a YouTube "
            "of ex-Atlassian employees that are laid off. Create the task for me "
            "in the goals."
        )
        model_title = "Create a backlog task . Basically, it is watching a YouTube of ex-A"

        title = local_store._clean_task_title(command, model_title)

        self.assertEqual(
            title,
            "Watch YouTube video about ex-Atlassian employees that are laid off",
        )
        self.assertNotIn("Create a backlog task", title)
        self.assertNotIn("Basically", title)

    def test_command_wrapper_is_removed_from_task_description(self) -> None:
        command = (
            "Create a backlog task in goals. Basically, it is watching a YouTube "
            "of ex-Atlassian employees that are laid off. Create the task for me "
            "in the goals."
        )
        model_payload = {
            "title": "Create a backlog task . Basically, it is watching a YouTube of ex-A",
            "description": (
                "Work on: Create a backlog task in . Basically, it is watching a "
                "YouTube of ex-Atlassian employees that are laid off. Create the "
                "task for me in the  goals.. Capture notes, progress, and next "
                "action when the focus session ends."
            ),
            "status": "backlog",
            "due_at": None,
            "tags": ["ai-draft"],
        }

        payload = local_store._normalize_task_payload(model_payload, command, {})

        self.assertEqual(
            payload["description"],
            "Watch the YouTube video about ex-Atlassian employees that are laid off. Capture key takeaways and any follow-up action.",
        )
        self.assertNotIn("Work on:", payload["description"])
        self.assertNotIn("Create a backlog task", payload["description"])

    def test_fragmented_create_title_falls_back_to_task_intent(self) -> None:
        command = (
            "Create a backlog task in goals. Basically, it is watching a YouTube "
            "of ex-Atlassian employees that are laid off. Create the task for me "
            "in the goals."
        )
        model_payload = {
            "title": "Create off",
            "description": "Watch off",
            "status": "backlog",
            "due_at": None,
            "tags": ["ai-draft"],
        }

        payload = local_store._normalize_task_payload(model_payload, command, {})

        self.assertEqual(
            payload["title"],
            "Watch YouTube video about ex-Atlassian employees that are laid off",
        )
        self.assertEqual(payload["status"], "backlog")
        self.assertNotIn("type", payload)
        self.assertNotIn("priority", payload)
        self.assertNotIn("goal_id", payload)

    def test_tag_names_resolve_to_existing_and_new_tags(self) -> None:
        existing = local_store.get_or_create_tag("Tech Study")

        task = local_store.create_task(
            {
                "title": "Watch YouTube video about laid-off ex-Atlassian employees",
                "description": "Watch and capture notes.",
                "due_at": None,
                "tag_ids": [existing["id"]],
                "tag_names": ["Tech Study", "Learning"],
            }
        )

        tag_names = {tag["name"] for tag in task["tags"]}
        self.assertEqual(tag_names, {"Tech Study", "Learning"})
        self.assertEqual(len(task["tags"]), 2)

    def test_create_ai_draft_and_confirm_creates_tagged_task(self) -> None:
        draft = local_store.create_ai_draft("Study Redis set vs sorted set")
        self.assertEqual(draft["action_type"], "create_task")
        self.assertEqual(draft["payload"]["status"], "backlog")

        confirmed = local_store.confirm_ai_draft(draft["id"])
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["result"]["status"], "backlog")


if __name__ == "__main__":
    unittest.main()
