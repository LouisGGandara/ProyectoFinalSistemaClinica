"""Tests for the simulated week of tests/bulk_demo.py.

They run a shorter week (120 patients, so the administrator comes four times
and tries every kind of undo) in a temporary folder, never in data/. The
week ends on a fixed Thursday at 13:00, so the dates are always the same.
"""

import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from models.actions import (
    CALL_NEXT,
    CARE_FINISHED,
    LOGIN,
    LOGOUT,
    PATIENT_REGISTRATION,
    PATIENT_UPDATE,
    TICKET_CANCELLATION,
    TICKET_CREATION,
    UNDONE,
    USER_MANAGEMENT,
)
from services.clinic_system import ClinicSystem
from tests.bulk_demo import (
    ADMIN,
    AFTERNOON_USER,
    CLOSING,
    OPENING,
    WOMEN_NAMES,
    SimulatedClock,
    SimulatedWeek,
    split_patients,
    work_days,
)
from utils.dates import DATE_FORMAT, set_clock

PATIENTS = 120
END = datetime(2026, 11, 5, 13, 0)  # a Thursday


class WorkDaysTest(unittest.TestCase):
    def test_five_weekdays_ending_now(self):
        days = work_days(END, 5)
        self.assertEqual(
            [opening.strftime("%a %d") for opening, _ in days],
            ["Fri 30", "Mon 02", "Tue 03", "Wed 04", "Thu 05"],
        )
        self.assertEqual(days[-1][1], END)
        self.assertEqual(days[0][1].time(), CLOSING)

    def test_a_too_short_today_is_left_out(self):
        days = work_days(datetime(2026, 11, 5, 7, 30), 5)
        self.assertEqual(days[-1][0].date(), datetime(2026, 11, 4).date())

    def test_patients_follow_the_length_of_each_day(self):
        counts = split_patients(300, work_days(END, 5))
        self.assertEqual(sum(counts), 300)
        self.assertLess(counts[-1], counts[0])  # today is only half a day


class SimulatedWeekTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._tmp.name) / "data"
        cls.system = ClinicSystem(str(cls.folder))
        days = work_days(END, 5)
        clock = SimulatedClock(days[0][0])
        set_clock(clock)
        try:
            week = SimulatedWeek(cls.system, random.Random(2026), clock, END)
            week.run(PATIENTS, show_progress=False)
        finally:
            set_clock(None)
        cls.stats = week.summary["stats"]
        cls.history = week.summary["history"]
        tickets = (cls.folder / "tickets.json").read_text(encoding="utf-8")
        cls.tickets = json.loads(tickets)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_registers_the_requested_number_of_patients(self):
        self.assertEqual(self.stats["registered_patients"], PATIENTS)

    def test_every_action_type_is_in_the_history(self):
        types = {action.action_type for action in self.history}
        expected = {
            LOGIN, LOGOUT, PATIENT_REGISTRATION, TICKET_CREATION, PATIENT_UPDATE,
            CALL_NEXT, CARE_FINISHED, TICKET_CANCELLATION, USER_MANAGEMENT, UNDONE,
        }
        self.assertEqual(expected - types, set())

    def test_every_undo_marks_its_action(self):
        undone = [a for a in self.history if getattr(a, "undone", False)]
        evidence = [a for a in self.history if a.action_type == UNDONE]
        self.assertEqual(len(undone), len(evidence))
        self.assertEqual(len(undone), 4)  # one per visit of the administrator

    def test_users_end_as_they_started(self):
        self.system.login(*ADMIN)
        try:
            usernames = [user.username for user in self.system.list_users()]
        finally:
            self.system.logout()
        self.assertEqual(usernames, ["admin", "recepcion"])
        self.assertNotIn(AFTERNOON_USER, usernames)

    def test_nobody_in_care_and_patients_still_waiting(self):
        # Whether the priority queue keeps someone depends on who arrives in
        # the last hour, so the test only asks for somebody waiting.
        self.assertEqual(self.stats["in_progress"], 0)
        for key in ("served", "cancelled", "pending"):
            with self.subTest(key=key):
                self.assertGreater(self.stats[key], 0)

    def test_dates_spread_over_the_five_days_in_working_hours(self):
        created = [datetime.strptime(row["created_at"], DATE_FORMAT) for row in self.tickets]
        self.assertEqual(len({moment.date() for moment in created}), 5)
        for moment in created:
            with self.subTest(moment=moment):
                self.assertGreaterEqual(moment.time(), OPENING)
                self.assertLessEqual(moment.time(), CLOSING)

    def test_tickets_keep_the_order_of_their_dates_and_none_is_in_the_future(self):
        rows = sorted(self.tickets, key=lambda row: int(row["number"].split("-")[1]))
        created = [datetime.strptime(row["created_at"], DATE_FORMAT) for row in rows]
        self.assertEqual(created, sorted(created))
        self.assertLessEqual(created[-1], END)
        stamps = [datetime.strptime(a.timestamp, DATE_FORMAT) for a in self.history]
        self.assertEqual(stamps, sorted(stamps, reverse=True))  # newest first

    def test_only_women_have_the_pregnancy_criterion(self):
        women = set(WOMEN_NAMES)
        patients = json.loads((self.folder / "patients.json").read_text(encoding="utf-8"))
        names = {row["code"]: row["full_name"] for row in patients}
        pregnant = [row for row in self.tickets if row["criterion"] == "Embarazo"]
        self.assertTrue(pregnant)
        for row in pregnant:
            with self.subTest(ticket=row["number"]):
                self.assertIn(names[row["patient_code"]].split()[0], women)

    def test_both_receptionists_served_patients(self):
        records = json.loads((self.folder / "care_records.json").read_text(encoding="utf-8"))
        self.assertEqual({row["served_by"] for row in records}, {"recepcion", AFTERNOON_USER})

    def test_reopening_gives_the_same_data_and_an_empty_history(self):
        reopened = ClinicSystem(str(self.folder))
        self.assertEqual(reopened.warnings, [])
        reopened.login(*ADMIN)
        self.assertEqual(reopened.stats(), self.stats)
        # Only the login just made: the history lives in memory (section 3.8).
        self.assertEqual(len(reopened.action_history()), 1)


if __name__ == "__main__":
    unittest.main()
