"""Tests for TicketQueue and Stack (step C5).

Run from the project root with: python -m unittest discover tests
"""

import unittest

from models.care_type import NormalCare, PriorityCare
from models.patient import Patient
from models.ticket import Ticket
from structures.stack import Stack
from structures.ticket_queue import TicketQueue
from utils.exceptions import (
    ClinicError,
    EmptyQueueError,
    EmptyStackError,
    NotFoundError,
    ValidationError,
)


def make_ticket(number: str, code: str = "PAC-0001") -> Ticket:
    """Build a Pending ticket. The prefix of the number picks the care type."""
    patient = Patient(code, "Ana López", 30, "55551234")
    care_type = PriorityCare("Embarazo") if number.startswith("P") else NormalCare()
    return Ticket(number, patient, care_type, "Dolor de cabeza")


def numbers(tickets: list[Ticket]) -> list[str]:
    return [ticket.number for ticket in tickets]


class TestTicketQueueBasics(unittest.TestCase):
    def setUp(self):
        self.queue = TicketQueue("Normal")
        self.t1 = make_ticket("N-001")
        self.t2 = make_ticket("N-002")
        self.t3 = make_ticket("N-003")

    def test_name_is_kept_and_read_only(self):
        self.assertEqual(self.queue.name, "Normal")
        with self.assertRaises(AttributeError):
            self.queue.name = "Otra"

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            TicketQueue("   ")

    def test_new_queue_is_empty(self):
        self.assertTrue(self.queue.is_empty())
        self.assertEqual(self.queue.count(), 0)
        self.assertEqual(len(self.queue), 0)
        self.assertEqual(self.queue.list_all(), [])

    def test_enqueue_adds_at_the_back(self):
        self.queue.enqueue(self.t1)
        self.queue.enqueue(self.t2)
        self.assertEqual(numbers(self.queue.list_all()), ["N-001", "N-002"])
        self.assertFalse(self.queue.is_empty())
        self.assertEqual(self.queue.count(), 2)
        self.assertEqual(len(self.queue), 2)

    def test_dequeue_follows_fifo_order(self):
        for ticket in (self.t1, self.t2, self.t3):
            self.queue.enqueue(ticket)
        served = [self.queue.dequeue() for _ in range(3)]
        self.assertEqual(served, [self.t1, self.t2, self.t3])
        self.assertTrue(self.queue.is_empty())

    def test_peek_returns_the_front_without_removing_it(self):
        self.queue.enqueue(self.t1)
        self.queue.enqueue(self.t2)
        self.assertIs(self.queue.peek(), self.t1)
        self.assertIs(self.queue.peek(), self.t1)
        self.assertEqual(self.queue.count(), 2)

    def test_list_all_is_a_copy(self):
        self.queue.enqueue(self.t1)
        copy = self.queue.list_all()
        copy.clear()
        self.assertEqual(self.queue.count(), 1)

    def test_queue_keeps_the_same_ticket_objects(self):
        self.queue.enqueue(self.t1)
        self.assertIs(self.queue.dequeue(), self.t1)

    def test_repr_lists_the_numbers(self):
        self.queue.enqueue(self.t1)
        self.queue.enqueue(self.t2)
        self.assertEqual(repr(self.queue), "TicketQueue('Normal': [N-001, N-002])")


class TestTicketQueueEmpty(unittest.TestCase):
    def setUp(self):
        self.queue = TicketQueue("Prioritaria")

    def test_dequeue_on_empty_queue_raises(self):
        with self.assertRaises(EmptyQueueError) as context:
            self.queue.dequeue()
        self.assertEqual(
            str(context.exception),
            "No hay turnos en espera en la cola Prioritaria.",
        )

    def test_peek_on_empty_queue_raises(self):
        with self.assertRaises(EmptyQueueError):
            self.queue.peek()

    def test_empty_queue_error_is_a_clinic_error(self):
        # The interface catches ClinicError, so this must not reach the user
        # as an unexpected error.
        with self.assertRaises(ClinicError):
            self.queue.dequeue()

    def test_queue_raises_again_after_being_emptied(self):
        self.queue.enqueue(make_ticket("P-001"))
        self.queue.dequeue()
        with self.assertRaises(EmptyQueueError):
            self.queue.dequeue()

    def test_failed_dequeue_leaves_the_queue_usable(self):
        with self.assertRaises(EmptyQueueError):
            self.queue.dequeue()
        ticket = make_ticket("P-002")
        self.queue.enqueue(ticket)
        self.assertIs(self.queue.dequeue(), ticket)


class TestTicketQueueUndoSupport(unittest.TestCase):
    """remove, insert_at and push_front: the operations behind cancel and undo."""

    def setUp(self):
        self.queue = TicketQueue("Normal")
        self.tickets = [make_ticket(f"N-00{i}") for i in range(1, 5)]
        for ticket in self.tickets:
            self.queue.enqueue(ticket)

    def test_remove_returns_the_position_and_takes_the_ticket_out(self):
        position = self.queue.remove(self.tickets[1])
        self.assertEqual(position, 1)
        self.assertEqual(numbers(self.queue.list_all()), ["N-001", "N-003", "N-004"])

    def test_remove_front_and_back(self):
        self.assertEqual(self.queue.remove(self.tickets[0]), 0)
        self.assertEqual(self.queue.remove(self.tickets[3]), 2)
        self.assertEqual(numbers(self.queue.list_all()), ["N-002", "N-003"])

    def test_remove_then_insert_at_restores_the_same_position(self):
        # Walkthrough 2 of step A3: cancel N-002, then undo.
        before = self.queue.list_all()
        position = self.queue.remove(self.tickets[1])
        self.queue.insert_at(position, self.tickets[1])
        self.assertEqual(self.queue.list_all(), before)

    def test_remove_then_insert_at_works_for_every_position(self):
        for ticket in list(self.tickets):
            before = self.queue.list_all()
            position = self.queue.remove(ticket)
            self.queue.insert_at(position, ticket)
            self.assertEqual(self.queue.list_all(), before)

    def test_remove_missing_ticket_raises_not_found(self):
        other = make_ticket("N-009")
        with self.assertRaises(NotFoundError) as context:
            self.queue.remove(other)
        self.assertIn("N-009", str(context.exception))
        self.assertEqual(self.queue.count(), 4)

    def test_remove_on_empty_queue_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            TicketQueue("Prioritaria").remove(self.tickets[0])

    def test_remove_compares_objects_not_numbers(self):
        # A different object with the same number is not the ticket in line.
        twin = make_ticket("N-002")
        with self.assertRaises(NotFoundError):
            self.queue.remove(twin)

    def test_insert_at_the_end_is_allowed(self):
        ticket = make_ticket("N-005")
        self.queue.insert_at(4, ticket)
        self.assertIs(self.queue.list_all()[-1], ticket)

    def test_insert_at_into_an_empty_queue(self):
        queue = TicketQueue("Prioritaria")
        ticket = make_ticket("P-001")
        queue.insert_at(0, ticket)
        self.assertIs(queue.peek(), ticket)

    def test_insert_at_invalid_position_raises(self):
        ticket = make_ticket("N-005")
        for position in (-1, 5, 99):
            with self.assertRaises(ValidationError):
                self.queue.insert_at(position, ticket)
        self.assertEqual(self.queue.count(), 4)

    def test_push_front_puts_the_ticket_first(self):
        first = self.queue.dequeue()
        self.queue.push_front(first)
        self.assertIs(self.queue.peek(), first)
        self.assertEqual(numbers(self.queue.list_all()),
                         ["N-001", "N-002", "N-003", "N-004"])

    def test_push_front_on_an_empty_queue(self):
        queue = TicketQueue("Prioritaria")
        ticket = make_ticket("P-001")
        queue.push_front(ticket)
        self.assertIs(queue.dequeue(), ticket)


class TestTwoQueuesWalkthrough(unittest.TestCase):
    """Walkthrough 1 of step A3, done by hand with two queues.

    TicketManager.call_next will apply the same rule in step C9: take from the
    priority queue first, and from the normal queue only if it is empty.
    """

    def test_priority_first_then_arrival_order(self):
        priority = TicketQueue("Prioritaria")
        normal = TicketQueue("Normal")
        arrivals = [make_ticket(n) for n in ("N-001", "N-002", "P-003", "N-004")]
        for ticket in arrivals:
            target = priority if ticket.care_type.is_priority else normal
            target.enqueue(ticket)

        served = []
        for _ in range(3):
            source = normal if priority.is_empty() else priority
            served.append(source.dequeue().number)

        self.assertEqual(served, ["P-003", "N-001", "N-002"])
        self.assertEqual(numbers(normal.list_all()), ["N-004"])
        self.assertTrue(priority.is_empty())


class TestStack(unittest.TestCase):
    def setUp(self):
        self.stack = Stack()

    def test_new_stack_is_empty(self):
        self.assertTrue(self.stack.is_empty())
        self.assertEqual(self.stack.count(), 0)
        self.assertEqual(len(self.stack), 0)
        self.assertEqual(self.stack.list_from_top(), [])

    def test_push_adds_on_top(self):
        self.stack.push("a")
        self.stack.push("b")
        self.assertEqual(self.stack.peek(), "b")
        self.assertEqual(self.stack.count(), 2)
        self.assertEqual(len(self.stack), 2)
        self.assertFalse(self.stack.is_empty())

    def test_pop_follows_lifo_order(self):
        for item in ("a", "b", "c"):
            self.stack.push(item)
        popped = [self.stack.pop() for _ in range(3)]
        self.assertEqual(popped, ["c", "b", "a"])
        self.assertTrue(self.stack.is_empty())

    def test_peek_does_not_remove(self):
        self.stack.push("a")
        self.assertEqual(self.stack.peek(), "a")
        self.assertEqual(self.stack.peek(), "a")
        self.assertEqual(self.stack.count(), 1)

    def test_list_from_top_shows_the_most_recent_first(self):
        for item in ("a", "b", "c"):
            self.stack.push(item)
        self.assertEqual(self.stack.list_from_top(), ["c", "b", "a"])

    def test_list_from_top_is_a_copy(self):
        self.stack.push("a")
        self.stack.list_from_top().clear()
        self.assertEqual(self.stack.count(), 1)

    def test_stack_keeps_the_same_objects(self):
        item = {"action_type": "Registro de paciente"}
        self.stack.push(item)
        self.assertIs(self.stack.pop(), item)

    def test_push_after_pop_goes_on_top(self):
        self.stack.push("a")
        self.stack.push("b")
        self.stack.pop()
        self.stack.push("c")
        self.assertEqual(self.stack.list_from_top(), ["c", "a"])

    def test_two_stacks_are_independent(self):
        # ActionHistory keeps two stacks; filling one must not touch the other.
        other = Stack()
        self.stack.push("a")
        self.assertTrue(other.is_empty())


class TestStackEmpty(unittest.TestCase):
    def setUp(self):
        self.stack = Stack()

    def test_pop_on_empty_stack_raises(self):
        with self.assertRaises(EmptyStackError) as context:
            self.stack.pop()
        self.assertEqual(
            str(context.exception),
            "No hay acciones que se puedan deshacer.",
        )

    def test_peek_on_empty_stack_raises(self):
        with self.assertRaises(EmptyStackError):
            self.stack.peek()

    def test_empty_stack_error_is_a_clinic_error(self):
        with self.assertRaises(ClinicError):
            self.stack.pop()

    def test_stack_raises_again_after_being_emptied(self):
        self.stack.push("a")
        self.stack.pop()
        with self.assertRaises(EmptyStackError):
            self.stack.pop()

    def test_failed_pop_leaves_the_stack_usable(self):
        with self.assertRaises(EmptyStackError):
            self.stack.pop()
        self.stack.push("a")
        self.assertEqual(self.stack.pop(), "a")


if __name__ == "__main__":
    unittest.main()
