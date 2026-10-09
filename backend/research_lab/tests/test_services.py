from unittest import mock

from django.test import SimpleTestCase

from research_lab.exceptions import BudgetExceeded, RunCancelled
from research_lab.services import dedup
from research_lab.services.resilience import Budget, retry_with_backoff
from research_lab.tests.fakes import make_candidate


class DedupTests(SimpleTestCase):
    def test_exact_doi_duplicate_is_removed(self):
        a = make_candidate('Paper A', doi='10.1/x')
        b = make_candidate('Paper A (mirror)', doi='10.1/X', url='https://mirror.example.com/a')
        self.assertEqual(dedup.dedupe_candidates([a, b]), [a])

    def test_exact_isbn_duplicate_is_removed(self):
        a = make_candidate('Deep Learning', isbn='978-0-262-03561-3')
        b = make_candidate('Deep Learning (2nd listing)', isbn='9780262035613')
        self.assertEqual(dedup.dedupe_candidates([a, b]), [a])

    def test_normalized_url_duplicate_is_removed(self):
        a = make_candidate('Lecture notes', url='https://Example.com/notes/')
        b = make_candidate('Lecture notes (dup)', url='http://example.com/notes?utm_source=x')
        self.assertEqual(dedup.dedupe_candidates([a, b]), [a])

    def test_fuzzy_title_author_year_duplicate_is_removed(self):
        from datetime import date

        a = make_candidate('Retrieval-Augmented Generation for NLP', authors=['Jane Doe'],
                           published_at=date(2023, 1, 1), url='https://a.example.com')
        b = make_candidate('Retrieval Augmented Generation for NLP', authors=['Jane Doe'],
                           published_at=date(2023, 6, 1), url='https://b.example.com')
        self.assertEqual(dedup.dedupe_candidates([a, b]), [a])

    def test_distinct_sources_are_kept(self):
        a = make_candidate('Paper A', doi='10.1/a')
        b = make_candidate('Completely different paper', doi='10.1/b')
        self.assertEqual(dedup.dedupe_candidates([a, b]), [a, b])

    def test_content_hash_is_stable_and_order_independent_of_whitespace(self):
        self.assertEqual(dedup.content_hash('hello world'), dedup.content_hash('hello world'))
        self.assertNotEqual(dedup.content_hash('hello world'), dedup.content_hash('hello worlds'))


class ResilienceTests(SimpleTestCase):
    def test_retry_succeeds_after_transient_failures(self):
        calls = {'n': 0}

        def flaky():
            calls['n'] += 1
            if calls['n'] < 3:
                raise ValueError('transient')
            return 'ok'

        with mock.patch('time.sleep'):
            self.assertEqual(retry_with_backoff(flaky, attempts=5, exceptions=(ValueError,)), 'ok')
        self.assertEqual(calls['n'], 3)

    def test_retry_gives_up_after_the_last_attempt(self):
        with mock.patch('time.sleep'):
            with self.assertRaises(ValueError):
                retry_with_backoff(lambda: (_ for _ in ()).throw(ValueError('nope')), attempts=2,
                                   exceptions=(ValueError,))

    def test_budget_enforces_step_and_time_limits(self):
        budget = Budget.start(max_steps=2, max_runtime_seconds=3600)
        budget.check(cancel_requested=False)
        budget.step()
        budget.check(cancel_requested=False)
        budget.step()
        with self.assertRaises(BudgetExceeded):
            budget.check(cancel_requested=False)

    def test_budget_enforces_cancellation(self):
        budget = Budget.start(max_steps=10, max_runtime_seconds=3600)
        with self.assertRaises(RunCancelled):
            budget.check(cancel_requested=True)

    def test_budget_enforces_wall_clock_timeout(self):
        budget = Budget.start(max_steps=100, max_runtime_seconds=0.0)
        with self.assertRaises(BudgetExceeded):
            budget.check(cancel_requested=False)
