from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from nova_school.registry import CourseRegistry
from nova_school.resolver import resolve_requested_course
from tools import class_capture as class_tools


class AnytimeClassResolutionTests(unittest.TestCase):
    def test_explicit_cot3400_works_independent_of_schedule(self):
        course = resolve_requested_course("COT-3400", registry=CourseRegistry())
        self.assertIsNotNone(course)
        self.assertEqual(course.code, "COT3400")

    def test_common_stt_one_letter_error_resolves_uniquely(self):
        course = resolve_requested_course("COG 3400", registry=CourseRegistry())
        self.assertIsNotNone(course)
        self.assertEqual(course.code, "COT3400")

    def test_numeric_suffix_can_resolve_when_unique(self):
        course = resolve_requested_course("3400", registry=CourseRegistry())
        self.assertIsNotNone(course)
        self.assertEqual(course.code, "COT3400")

    def test_no_schedule_does_not_launch_worker(self):
        with (
            patch.object(class_tools, "read_active_session", return_value=None),
            patch.object(class_tools, "resolve_current_course", return_value=None),
            patch.object(class_tools, "_launch_capture_worker") as launch,
        ):
            result = asyncio.run(class_tools.start_class_capture(""))
        launch.assert_not_called()
        self.assertIn("record class at any time", result)
        self.assertIn("which class", result.lower())

    def test_explicit_request_is_canonicalized_before_worker_launch(self):
        class Active:
            course = "COT3400"
            session_id = "anytime-test"

        with (
            patch.object(class_tools, "read_active_session", return_value=None),
            patch.object(class_tools, "_launch_capture_worker", return_value=123) as launch,
            patch.object(class_tools, "_wait_for_active_capture", return_value=Active()),
        ):
            result = asyncio.run(class_tools.start_class_capture("COG-3400"))

        launch.assert_called_once_with("COT3400")
        self.assertIn("active for COT3400", result)


    def test_failed_start_cleans_launched_process(self):
        with (
            patch.object(class_tools, "read_active_session", return_value=None),
            patch.object(
                class_tools,
                "_resolve_course_for_start",
                return_value=(type("Course", (), {"code": "COT3400"})(), "test"),
            ),
            patch.object(class_tools, "_launch_capture_worker", return_value=123),
            patch.object(class_tools, "_wait_for_active_capture", return_value=None),
            patch.object(
                class_tools,
                "close_capture_launcher_tree",
                return_value="class capture process tree closed (2 process(es))",
            ) as cleanup,
            patch.object(class_tools, "_launcher_log_tail", return_value=""),
        ):
            result = asyncio.run(class_tools.start_class_capture("COT3400"))

        cleanup.assert_called_once_with(123)
        self.assertIn("did not become healthy", result)
        self.assertIn("Launch cleanup", result)


if __name__ == "__main__":
    unittest.main()
