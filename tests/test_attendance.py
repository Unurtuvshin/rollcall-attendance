import unittest
from datetime import datetime
from attendance import entry_status, exit_status

LESSON = {"day": "2026-11-04", "first_start": "09:00", "first_end": "09:45",
          "second_start": "09:45", "second_end": "10:30"}  # one 90-minute lesson in two 45-minute parts


def at(clock):
    return datetime.fromisoformat("2026-11-04T" + clock + "+09:00")


class DecisionTableTests(unittest.TestCase):
    def test_entry_rows_and_boundaries(self):
        cases = [
            ("08:30:00", ("present", "present")),
            ("09:00:00", ("present", "present")),
            ("09:00:01", ("late", "present")),
            ("09:15:00", ("late", "present")),
            ("09:15:01", ("absent", "present")),
            ("09:45:00", ("absent", "present")),
            ("09:45:01", ("absent", "late")),
            ("10:00:00", ("absent", "late")),
            ("10:00:01", ("absent", "absent")),
            ("10:30:00", ("absent", "absent")),
        ]
        for clock, expected in cases:
            with self.subTest(clock=clock):
                self.assertEqual(entry_status(LESSON, at(clock)), expected)

    def test_outside_entry_window(self):
        with self.assertRaises(ValueError):
            entry_status(LESSON, at("08:29:59"))

    def test_entry_after_class_end_is_absent(self):
        self.assertEqual(entry_status(LESSON, at("10:30:01")), ("absent", "absent"))

    def test_exit_rows_and_boundaries(self):
        cases = [
            ("09:15:00", ("absent", "absent")),
            ("09:29:59", ("absent", "absent")),
            ("09:30:00", ("early", "absent")),
            ("09:45:00", ("early", "absent")),
            ("09:45:01", ("present", "absent")),
            ("10:00:00", ("present", "absent")),
            ("10:14:59", ("present", "absent")),
            ("10:15:00", ("present", "early")),
            ("10:30:00", ("present", "early")),
            ("10:30:01", ("present", "present")),
        ]
        for clock, expected in cases:
            with self.subTest(clock=clock):
                self.assertEqual(exit_status(LESSON, at("08:55:00"), at(clock)), expected)

    def test_exit_preserves_first_entry_judgement(self):
        self.assertEqual(exit_status(LESSON, at("09:05:00"), at("10:00:00")), ("late", "absent"))
        self.assertEqual(exit_status(LESSON, at("09:30:00"), at("10:20:00")), ("absent", "early"))

    def test_exit_cannot_improve_absence(self):
        self.assertEqual(exit_status(LESSON, at("09:50:00"), at("10:20:00")), ("absent", "early"))
        self.assertEqual(exit_status(LESSON, at("10:05:00"), at("10:20:00")), ("absent", "absent"))
        self.assertEqual(exit_status(LESSON, at("09:20:00"), at("09:40:00")), ("absent", "absent"))

    def test_exit_must_follow_entry(self):
        with self.assertRaises(ValueError):
            exit_status(LESSON, at("09:00:00"), at("08:59:00"))


if __name__ == "__main__":
    unittest.main()
