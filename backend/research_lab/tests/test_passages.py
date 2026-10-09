"""Picking the relevant part of a long document without a model (``services/passages.py``)."""
import time

from django.test import SimpleTestCase, override_settings

from core.testing import BaseTestCase
from research_lab.agents.assignment_generator import _format_sources
from research_lab.models import DocumentStatus, ResearchDocument, ResearchSource
from research_lab.services import passages
from research_lab.tests.test_workflow import make_run


def book(chapters: int = 120) -> str:
    """A fake 200-page book: many unrelated chapters, with one chapter about hash tables buried in it."""
    filler = ('The committee reviewed the budget for the next fiscal year and discussed the schedule of '
              'meetings, the allocation of rooms and the printing of the annual report. ') * 6
    parts = [f'Chapter {i}: Administrative matters {i}\n\n{filler}' for i in range(chapters)]
    parts[77] = ('Chapter 77: Hash tables\n\nA hash table maps keys to buckets using a hash function. '
                 'Collisions are resolved by chaining or open addressing. ' * 5
                 + '\n\nThe load factor of a hash table controls resizing; a good hash function spreads keys evenly.')
    return '\n\n'.join(parts)


class SelectContextTests(SimpleTestCase):
    def test_a_long_book_yields_the_relevant_chapter_within_the_budget(self):
        text = book()
        self.assertGreater(len(text), 100_000)
        excerpt = passages.select_context(text, 'Hash tables', 4000)
        self.assertLessEqual(len(excerpt), 4200)
        self.assertIn('Chapter 77: Hash tables', excerpt)
        self.assertIn('load factor', excerpt)
        self.assertNotIn('Chapter 5:', excerpt)  # unrelated chapters are left out

    def test_excerpts_keep_document_order_and_mark_gaps(self):
        text = 'Intro paragraph about loops. ' * 30 + '\n\n' + 'unrelated filler text here. ' * 60 + '\n\n' \
               + 'Python for loops iterate over a sequence; loops can be nested. ' * 20 + '\n\n' \
               + 'more filler about weather and travel. ' * 80
        excerpt = passages.select_context(text, 'python loops', 1800)
        self.assertLess(excerpt.index('Intro paragraph'), excerpt.index('Python for loops'))
        self.assertIn('[…]', excerpt)

    def test_short_documents_are_returned_whole(self):
        text = 'A short note about hash tables.'
        self.assertEqual(passages.select_context(text, 'hash tables', 5000), text)

    def test_no_keyword_match_falls_back_to_the_opening(self):
        text = '\n\n'.join(f'Paragraph {i} about gardening and soil. ' * 30 for i in range(40))
        excerpt = passages.select_context(text, 'quantum chromodynamics', 2000)
        self.assertTrue(excerpt.startswith('Paragraph 0'))

    def test_reference_lists_are_not_preferred_over_prose(self):
        prose = 'Hash tables store entries in buckets and resolve collisions. ' * 12
        refs = 'References\n' + '\n'.join(f'[{i}] Smith, J. Hash tables. doi.org/10.1/{i} http://x.org/{i}' for i in range(20))
        text = ('padding words. ' * 400) + '\n\n' + refs + '\n\n' + prose + '\n\n' + ('padding words. ' * 400)
        excerpt = passages.select_context(text, 'hash tables', 1200)
        self.assertIn('resolve collisions', excerpt)
        self.assertNotIn('doi.org', excerpt)

    def test_light_stemming_matches_word_forms(self):
        self.assertEqual(passages.tokens('Looping loops looped'), ['loop', 'loop', 'loop'])

    def test_it_is_fast_enough_for_a_whole_book(self):
        text = book(400)
        started = time.perf_counter()
        passages.select_context(text, 'Hash tables', 6000)
        self.assertLess(time.perf_counter() - started, 3.0)


class FormatSourcesTests(BaseTestCase):
    @override_settings(RESEARCH_LAB_CONTEXT_CHARS=6000)
    def test_writers_get_excerpts_of_the_full_text_not_just_the_abstract(self):
        run = make_run(topic='Hash tables')
        source = ResearchSource.objects.create(run=run, provider='BRIGHTDATA', external_id='b', title='Algorithms book',
                                               abstract='A general book.')
        ResearchDocument.objects.create(source=source, status=DocumentStatus.EXTRACTED, text=book(), text_length=len(book()))
        text = _format_sources([ResearchSource.objects.get(pk=source.pk)], 'Hash tables')
        self.assertIn('load factor', text)
        self.assertLess(len(text), 6500)
        self.assertIn('(id=', text)
