"""Materials search: the new sources, per-source switches, the download policy, stored originals,
full text and the LLM-ready context. All network I/O is mocked."""
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings

from core.testing import BaseTestCase, api_client, make_admin, make_llm_config, make_student, make_teacher, pdf_bytes
from research_lab.agents import academic_research, document_analysis, document_retrieval, web_research
from research_lab.agents.boss import run_workflow
from research_lab.exceptions import FetchError, ProviderError
from research_lab.models import (DocumentStatus, ModuleSettings, ResearchDocument, ResearchRun, ResearchSource,
                                 RunMode, SourceProvider)
from research_lab.providers.search.brightdata import BrightDataSearchProvider, _organic_results
from research_lab.providers.search.core_ac import CoreProvider
from research_lab.providers.search.open_library import OpenLibraryProvider
from research_lab.providers.search.wikipedia import WikipediaProvider
from research_lab.providers.search.youtube import YouTubeProvider
from research_lab.schemas import FetchResult
from research_lab.services import fetcher, module_settings, provider_gate
from research_lab.services.resilience import Budget
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_fetch, patch_providers
from research_lab.tests.test_workflow import make_run


def resp(status_code, **kw):
    return httpx.Response(status_code, request=httpx.Request('GET', 'https://example.com'), **kw)


def analyze_documents(run, candidates, budget):
    """Document Retrieval (download) followed by Document Analysis (extract), as the Boss runs them."""
    _, sources = document_retrieval.run(run, 1, candidates, budget)
    return document_analysis.run(run, 2, sources, budget)


def search_run(**kw) -> ResearchRun:
    kw.setdefault('mode', RunMode.SEARCH)
    kw.setdefault('generate_assignment', False)
    return make_run(**kw)


class NewProviderTests(SimpleTestCase):
    @override_settings(CORE_API_KEY='k')
    def test_core_keeps_the_api_full_text_and_the_pdf_link(self):
        body = {'results': [{'id': 7, 'title': 'Hashing', 'doi': 'https://doi.org/10.1/x', 'downloadUrl': 'https://core/x.pdf',
                             'fullText': 'full text ' * 50, 'abstract': 'abs', 'authors': [{'name': 'A. Author'}]}]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)) as get:
            (item,) = CoreProvider().search('hash', limit=5)
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer k')
        self.assertEqual((item.pdf_url, item.doi, item.authors), ('https://core/x.pdf', '10.1/x', ['A. Author']))
        self.assertTrue(item.full_text.startswith('full text'))

    @override_settings(CORE_API_KEY='')
    def test_core_without_a_key_reports_the_missing_setting(self):
        provider = CoreProvider()
        self.assertFalse(provider.configured())
        self.assertEqual(provider.missing_settings(), ['CORE_API_KEY'])

    def test_open_library_is_a_metadata_only_catalogue(self):
        body = {'docs': [{'title': 'Algorithms', 'key': '/works/OL1W', 'author_name': ['D. Knuth'],
                          'first_publish_year': 1968, 'subject': ['Sorting', 'Hashing'], 'isbn': ['9780201896831']}]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)):
            (item,) = OpenLibraryProvider().search('hash', limit=5)
        self.assertTrue(OpenLibraryProvider.metadata_only)
        self.assertEqual((item.url, item.isbn), ('https://openlibrary.org/works/OL1W', '9780201896831'))
        self.assertIn('Hashing', item.abstract)

    def test_wikipedia_identifies_itself_and_builds_article_urls(self):
        body = {'query': {'search': [{'title': 'Hash table', 'snippet': 'a <span>data</span> structure', 'pageid': 1}]}}
        with mock.patch('httpx.get', return_value=resp(200, json=body)) as get:
            (item,) = WikipediaProvider().search('hash table', limit=3)
        self.assertIn('ResearchLab', get.call_args.kwargs['headers']['User-Agent'])
        self.assertEqual((item.url, item.abstract), ('https://en.wikipedia.org/wiki/Hash_table', 'a data structure'))

    @override_settings(YOUTUBE_API_KEY='yt')
    def test_youtube_returns_video_descriptions_not_transcripts(self):
        body = {'items': [{'id': {'videoId': 'abc'}, 'snippet': {'title': 'Hash tables explained',
                'description': 'Lecture 5', 'channelTitle': 'MIT', 'publishedAt': '2020-01-02T00:00:00Z'}}]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)):
            (item,) = YouTubeProvider().search('hash tables', limit=3)
        self.assertEqual((item.url, item.source_type, item.abstract), ('https://www.youtube.com/watch?v=abc', 'VIDEO', 'Lecture 5'))

    @override_settings(YOUTUBE_API_KEY='')
    def test_youtube_is_unusable_without_a_key(self):
        self.assertEqual(YouTubeProvider().missing_settings(), ['YOUTUBE_API_KEY'])

    def test_bright_data_parses_json_wrapped_json_and_html(self):
        organic = [{'link': 'https://u.edu/a.pdf', 'title': 'A', 'description': 'd'}]
        import json
        self.assertEqual(_organic_results(json.dumps({'organic': organic})), organic)
        self.assertEqual(_organic_results(json.dumps({'status_code': 200, 'body': json.dumps({'organic': organic})})), organic)
        html = '<html><body><a href="/url?q=https://u.edu/b.pdf&sa=U">Notes B</a><a href="https://www.google.com/x">g</a></body></html>'
        self.assertEqual(_organic_results(html), [{'title': 'Notes B', 'link': 'https://u.edu/b.pdf', 'description': ''}])
        for bad in ('', '{"nothing": 1}', 'plain text'):
            with self.assertRaises(ValueError):
                _organic_results(bad)

    @override_settings(BRIGHTDATA_API_TOKEN='t', BRIGHTDATA_SERP_ZONE='z')
    def test_bright_data_results_carry_a_format_hint_and_no_duplicates(self):
        body = {'organic': [{'link': 'https://u.edu/a.pdf', 'title': 'A'}, {'link': 'https://u.edu/a.pdf', 'title': 'A again'},
                            {'link': 'https://u.edu/s.pptx', 'title': 'S'}]}
        with mock.patch('httpx.post', return_value=resp(200, json=body)):
            results = BrightDataSearchProvider().search('hash tables', limit=10)
        self.assertEqual([(r.url, r.metadata['format_hint']) for r in results],
                         [('https://u.edu/a.pdf', 'pdf'), ('https://u.edu/s.pptx', 'pptx')])


class SourceSwitchTests(BaseTestCase):
    def test_a_run_can_be_limited_to_the_sources_the_teacher_picked(self):
        run = search_run(selected_providers=['ARXIV'])
        arxiv, openalex = FakeProvider('ARXIV', [make_candidate('A', provider='ARXIV')]), FakeProvider('OPENALEX', [make_candidate('B')])
        with patch_providers(academic=[arxiv, openalex]):
            _, candidates = academic_research.run(run, 1)
        self.assertEqual(([c.title for c in candidates], openalex.calls), (['A'], []))

    def test_global_switch_and_run_selection_both_apply(self):
        ModuleSettings.objects.update_or_create(pk=1, defaults={'disabled_providers': ['ARXIV']})
        run = search_run(selected_providers=['ARXIV', 'OPENALEX'])
        self.assertEqual(provider_gate.allowed(run, FakeProvider('ARXIV')), (False, 'disabled in settings'))
        self.assertEqual(provider_gate.allowed(run, FakeProvider('OPENALEX')), (True, ''))
        self.assertEqual(provider_gate.allowed(run, FakeProvider('CROSSREF'))[0], False)

    def test_only_multi_query_sources_get_the_query_variants(self):
        class Multi(FakeProvider):
            multi_query = True

        run = search_run(topic='Hash tables')
        multi, single = Multi('BRIGHTDATA'), FakeProvider('WIKIPEDIA')
        with patch_providers(web=[multi, single]):
            web_research.run(run, 1)
        self.assertGreater(len(multi.calls), 1)
        self.assertEqual(single.calls, ['Hash tables'])

    def test_an_unconfigured_source_is_skipped_with_the_missing_key_named(self):
        run = search_run()
        provider = FakeProvider('CORE', [make_candidate('x')], is_configured=False)
        provider.missing_settings = lambda: ['CORE_API_KEY']
        with patch_providers(academic=[provider]):
            _, candidates = academic_research.run(run, 1)
        tool = run.tool_executions.get(tool='CORE')
        self.assertEqual((candidates, tool.status, tool.response_summary['reason']),
                         ([], 'SKIPPED', 'API key missing: CORE_API_KEY'))


class SourceStatusTests(BaseTestCase):
    def setUp(self):
        self.provider = FakeProvider('CORE')
        self.provider.missing_settings = lambda: []

    def state(self):
        return module_settings.provider_status(self.provider, ModuleSettings.load())['state']

    def test_active_disabled_missing_key_and_error(self):
        self.assertEqual(self.state(), 'active')
        provider_gate.record_health('CORE', False, 'HTTP 503 https://x?key=SECRET123')
        self.assertEqual(self.state(), 'error')
        status = module_settings.provider_status(self.provider, ModuleSettings.load())
        self.assertNotIn('SECRET123', status['last_error'])
        provider_gate.record_health('CORE', True)
        self.assertEqual(self.state(), 'active')
        self.provider._is_configured = False
        self.provider.missing_settings = lambda: ['CORE_API_KEY']
        self.assertEqual(self.state(), 'missing_key')
        ModuleSettings.objects.filter(pk=1).update(disabled_providers=['CORE'])
        self.assertEqual(self.state(), 'disabled')  # an explicit off switch wins over everything else

    def test_test_endpoint_records_the_outcome_and_is_admin_only(self):
        with patch_providers(academic=[FakeProvider('ARXIV', [make_candidate('x')], fail=True)]):
            denied = api_client(make_teacher()).post('/api/v1/research-lab/settings/providers/ARXIV/test/')
            ok = api_client(make_admin()).post('/api/v1/research-lab/settings/providers/ARXIV/test/')
            missing = api_client(make_admin()).post('/api/v1/research-lab/settings/providers/NOPE/test/')
        self.assertEqual((denied.status_code, missing.status_code), (403, 404))
        self.assertEqual((ok.data['state'], 'down' in ok.data['last_error']), ('error', True))

    def test_every_requested_source_is_registered_and_switchable(self):
        codes = {str(p.code) for p in module_settings.all_providers()}
        self.assertTrue({'OPENALEX', 'CORE', 'CROSSREF', 'GOOGLE_BOOKS', 'OPEN_LIBRARY', 'ARXIV', 'WIKIPEDIA',
                         'YOUTUBE', 'BRIGHTDATA'} <= codes)
        response = api_client(make_admin()).patch('/api/v1/research-lab/settings/', {'disabled_providers': ['CORE', 'YOUTUBE']}, format='json')
        self.assertEqual(response.status_code, 200)
        states = {p['code']: p['state'] for p in response.data['providers']}
        self.assertEqual((states['CORE'], states['YOUTUBE']), ('disabled', 'disabled'))


class FakePdfFetch:
    """fetch_url replacement serving a real one-page PDF for any URL."""

    def __init__(self, text='Hash tables map keys to buckets.'):
        self.pdf = pdf_bytes([text])
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if 'wikipedia' in url:  # an encyclopedia article is an HTML page: stored as text only
            return FetchResult(content=b'<html><body><article>A hash table is a data structure.</article></body></html>',
                               content_type='HTML', final_url=url, fetch_method='HTTP', latency_ms=3)
        return FetchResult(content=self.pdf, content_type='PDF', final_url=url, fetch_method='HTTP', latency_ms=3)


class DownloadPolicyTests(BaseTestCase):
    def run_documents(self, run, candidates, fetch):
        budget = Budget.start(max_steps=500, max_runtime_seconds=600)
        with mock.patch('research_lab.agents.document_retrieval.fetch_url', side_effect=fetch), \
                patch_providers(web=[FakeProvider('X')], academic=[FakeProvider('CROSSREF')]):
            analyze_documents(run, candidates, budget)

    @override_settings(RESEARCH_LAB_FETCH_PER_PROVIDER=2)
    def test_downloads_are_limited_per_source_but_every_result_is_listed(self):
        run = search_run()
        candidates = [make_candidate(f'Paper {i}', provider='ARXIV', url=f'https://arxiv.org/abs/{i}',
                                     pdf_url=f'https://arxiv.org/pdf/{i}', abstract=f'abstract {i}') for i in range(5)]
        fetch = FakePdfFetch()
        self.run_documents(run, candidates, fetch)
        self.assertEqual(len(fetch.urls), 2)
        self.assertEqual(run.sources.count(), 5)  # a search lists everything it found
        skipped = ResearchDocument.objects.filter(source__run=run, status=DocumentStatus.SKIPPED)
        self.assertEqual(skipped.count(), 3)
        self.assertTrue(all(d.text.startswith('abstract') and 'limit' in d.error_message for d in skipped))

    def test_metadata_only_sources_are_never_downloaded(self):
        run = search_run()
        crossref = FakeProvider('CROSSREF')
        crossref.metadata_only = True
        fetch = FakePdfFetch()
        budget = Budget.start(max_steps=50, max_runtime_seconds=60)
        with mock.patch('research_lab.agents.document_retrieval.fetch_url', side_effect=fetch), \
                patch_providers(academic=[crossref]):
            analyze_documents(run, [make_candidate('A', provider='CROSSREF', abstract='Only an abstract.')], budget)
        self.assertEqual(fetch.urls, [])
        document = ResearchDocument.objects.get(source__run=run)
        self.assertEqual((document.status, document.text), (DocumentStatus.SKIPPED, 'Only an abstract.'))

    def test_a_pdf_is_stored_extracted_and_served_inline(self):
        run = search_run(user=make_teacher())
        fetch = FakePdfFetch('Open addressing resolves collisions by probing.')
        self.run_documents(run, [make_candidate('Hashing', provider='ARXIV', pdf_url='https://arxiv.org/pdf/1.pdf')], fetch)
        source = run.sources.get()
        document = source.document
        self.assertEqual((document.content_type, document.status, document.mime_type), ('PDF', DocumentStatus.EXTRACTED, 'application/pdf'))
        self.assertTrue(document.file_name.endswith('.pdf') and document.file_size > 0)
        self.assertIn('Open addressing', document.text)
        client = api_client(run.user)
        inline = client.get(f'/api/v1/research-lab/runs/{run.pk}/sources/{source.pk}/file/')
        self.assertEqual(inline.status_code, 200)
        self.assertIn('inline', inline['Content-Disposition'])
        self.assertEqual(b''.join(inline.streaming_content)[:5], b'%PDF-')
        attachment = client.get(f'/api/v1/research-lab/runs/{run.pk}/sources/{source.pk}/file/?download=1')
        self.assertIn('attachment', attachment['Content-Disposition'])

    def test_full_text_from_the_api_survives_a_failed_download(self):
        run = search_run()
        candidate = make_candidate('Core paper', provider='CORE', pdf_url='https://core/x.pdf', full_text='The complete paper. ' * 40)

        def failing(url):
            raise FetchError('Access denied (HTTP 403); not downloaded.')

        self.run_documents(run, [candidate], failing)
        document = ResearchDocument.objects.get(source__run=run)
        self.assertEqual(document.status, DocumentStatus.FAILED)
        self.assertTrue(document.text.startswith('The complete paper.'))

    def test_identical_documents_are_flagged_as_duplicates(self):
        run = search_run()
        candidates = [make_candidate('First', provider='ARXIV', pdf_url='https://a/1.pdf'),
                      make_candidate('Second', provider='OPENALEX', pdf_url='https://b/2.pdf')]
        self.run_documents(run, candidates, FakePdfFetch())
        self.assertEqual(run.sources.filter(is_duplicate=True).count(), 1)
        listed = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/sources/').data['results']
        self.assertEqual(len(listed), 1)  # duplicates are hidden unless asked for
        everything = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/sources/?duplicates=1').data['results']
        self.assertEqual(len(everything), 2)


class AccessDeniedTests(SimpleTestCase):
    def test_a_403_is_not_worked_around(self):
        response = mock.MagicMock(status_code=403)
        error = httpx.HTTPStatusError('forbidden', request=mock.Mock(), response=response)
        with mock.patch.object(fetcher, '_fetch_http', side_effect=error), \
                mock.patch.object(fetcher, '_try_playwright') as playwright, \
                mock.patch.object(fetcher, 'fetch_via_unlocker') as unlocker:
            with self.assertRaisesMessage(FetchError, 'Access denied (HTTP 403)'):
                fetcher.fetch_url('https://paywalled.example.com/paper.pdf')
        playwright.assert_not_called()
        unlocker.assert_not_called()

    def test_content_type_detection_covers_the_stored_formats(self):
        detect = fetcher._detect_content_type
        self.assertEqual(detect('application/octet-stream', 'https://x/y', b'%PDF-1.7 ...'), 'PDF')
        self.assertEqual(detect('', 'https://x/slides.pptx?download=1'), 'PPTX')
        self.assertEqual(detect('text/plain', 'https://x/notes.txt', b'plain notes'), 'TXT')
        self.assertEqual(detect('text/html', 'https://x/page', b'<html>'), 'HTML')


class MaterialsApiTests(BaseTestCase):
    def setUp(self):
        make_llm_config()
        self.teacher = make_teacher()
        self.client = api_client(self.teacher)

    def finished_search(self):
        run = search_run(user=self.teacher, topic='Hash tables')
        web = [FakeProvider('WIKIPEDIA', [make_candidate('Hash table', provider='WIKIPEDIA', source_type='ENCYCLOPEDIA', url='https://en.wikipedia.org/wiki/Hash_table')])]
        academic = [FakeProvider('ARXIV', [make_candidate('Hashing paper', provider='ARXIV', pdf_url='https://arxiv.org/pdf/9.pdf',
                                                          abstract='short abstract')])]
        fetch = FakePdfFetch('Chaining stores colliding keys in a list.')
        with patch_providers(web=web, academic=academic), mock.patch('research_lab.agents.document_retrieval.fetch_url', side_effect=fetch):
            run_workflow(run.pk)
        run.refresh_from_db()
        return run

    def test_a_search_run_stops_after_document_analysis(self):
        run = self.finished_search()
        agents = set(run.agent_executions.values_list('agent', flat=True))
        self.assertEqual(run.status, 'COMPLETED')
        self.assertFalse({'SOURCE_VALIDATOR', 'LECTURE_BUILDER', 'ASSIGNMENT_GENERATOR', 'FINAL_REVIEWER'} & agents)
        self.assertTrue({'WEB_RESEARCH', 'ACADEMIC_RESEARCH', 'DOCUMENT_ANALYSIS'} <= agents)

    def test_creating_a_search_through_the_api_forces_generation_off(self):
        response = self.client.post('/api/v1/research-lab/runs/', {
            'topic': 'Hash tables', 'mode': 'SEARCH', 'selected_providers': ['ARXIV', 'WIKIPEDIA'],
            'generate_assignment': True, 'generate_lecture': True, 'llm_mode': 'LOCAL'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data['mode'], response.data['generate_assignment'], response.data['generate_lecture']),
                         ('SEARCH', False, False))
        bad = self.client.post('/api/v1/research-lab/runs/', {'topic': 'x', 'selected_providers': ['NOPE']}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_list_filters_detail_text_and_context(self):
        run = self.finished_search()
        base = f'/api/v1/research-lab/runs/{run.pk}'
        everything = self.client.get(f'{base}/sources/').data['results']
        self.assertEqual({r['provider'] for r in everything}, {'WIKIPEDIA', 'ARXIV'})
        self.assertEqual([r['provider'] for r in self.client.get(f'{base}/sources/?provider=arxiv').data['results']], ['ARXIV'])
        # every downloaded original is kept, HTML pages included
        self.assertEqual([r['provider'] for r in self.client.get(f'{base}/sources/?downloaded=1').data['results']], ['ARXIV', 'WIKIPEDIA'])
        self.assertEqual([r['provider'] for r in self.client.get(f'{base}/sources/?document_format=pdf').data['results']], ['ARXIV'])
        self.assertEqual([r['provider'] for r in self.client.get(f'{base}/sources/?document_format=html').data['results']], ['WIKIPEDIA'])

        paper = next(r for r in everything if r['provider'] == 'ARXIV')
        self.assertEqual((paper['document_format'], paper['has_file'], paper['document_status']), ('PDF', True, 'EXTRACTED'))
        detail = self.client.get(f"{base}/sources/{paper['id']}/").data
        self.assertIn('Chaining stores colliding keys', detail['text'])  # the full document text, not the abstract
        self.assertEqual(detail['text_origin'], 'document')

        context = self.client.get(f'{base}/context/').data
        self.assertEqual((context['materials'], context['topic']), (2, 'Hash tables'))
        self.assertIn('Chaining stores colliding keys', context['text'])
        download = self.client.get(f'{base}/context/?download=1')
        self.assertEqual(download['Content-Type'], 'text/plain; charset=utf-8')
        self.assertIn('attachment', download['Content-Disposition'])

    def test_materials_are_private_to_their_owner(self):
        run = self.finished_search()
        source = run.sources.first()
        for user in (make_teacher(), make_student()):
            client = api_client(user)
            for path in ('', f'{source.pk}/', f'{source.pk}/file/'):
                status = client.get(f'/api/v1/research-lab/runs/{run.pk}/sources/{path}').status_code
                self.assertIn(status, (403, 404), path)
        self.assertEqual(self.client.get(f'/api/v1/research-lab/runs/{run.pk}/sources/999999/').status_code, 404)
        html_source = run.sources.get(provider='WIKIPEDIA')
        html = self.client.get(f'/api/v1/research-lab/runs/{run.pk}/sources/{html_source.pk}/file/')
        self.assertEqual(html.status_code, 200)
        self.assertIn('attachment', html['Content-Disposition'])  # only PDFs are ever shown inline


class ProvisionalSourcesTests(BaseTestCase):
    def source(self, run, title, decision, score):
        return ResearchSource.objects.create(run=run, provider='BRIGHTDATA', external_id=title, title=title,
                                             decision=decision, overall_score=score)

    def test_a_single_approved_source_is_topped_up_with_the_best_reviewed_ones(self):
        from research_lab.agents import source_validator

        run = make_run()
        accepted = self.source(run, 'accepted', 'ACCEPT', 75)
        reviewed = [self.source(run, f'review {score}', 'REVIEW', score) for score in (62, 55, 48, 40, 20)]
        rejected = self.source(run, 'rejected', 'REJECT', 30)
        result = source_validator.with_provisional(run, [accepted], [accepted, *reviewed, rejected])
        self.assertEqual([s.title for s in result], ['accepted', 'review 62', 'review 55', 'review 48'])

    def test_enough_approved_sources_are_left_alone(self):
        from research_lab.agents import source_validator

        run = make_run()
        accepted = [self.source(run, f'a{i}', 'ACCEPT', 80) for i in range(4)]
        self.assertEqual(source_validator.with_provisional(run, accepted, accepted), accepted)


class ToolCallResponseTests(BaseTestCase):
    def test_a_search_call_keeps_what_the_source_returned(self):
        run = search_run()
        provider = FakeProvider('ARXIV', [make_candidate('Hashing paper', provider='ARXIV', abstract='x' * 500,
                                                         pdf_url='https://arxiv.org/pdf/1.pdf', authors=['A', 'B'])])
        with patch_providers(academic=[provider]):
            academic_research.run(run, 1)
        response = run.tool_executions.get(tool='ARXIV').response_summary
        self.assertEqual(response['count'], 1)
        (item,) = response['results']
        self.assertEqual((item['title'], item['pdf_url'], item['authors']), ('Hashing paper', 'https://arxiv.org/pdf/1.pdf', ['A', 'B']))
        self.assertTrue(item['abstract'].endswith('…') and len(item['abstract']) < 400)  # compact, not the whole abstract

    def test_download_and_extraction_calls_keep_their_details(self):
        run = search_run()
        budget = Budget.start(max_steps=50, max_runtime_seconds=60)
        with mock.patch('research_lab.agents.document_retrieval.fetch_url', side_effect=FakePdfFetch('Chaining resolves collisions.')), \
                patch_providers(academic=[FakeProvider('ARXIV')]):
            analyze_documents(run, [make_candidate('Paper', provider='ARXIV', pdf_url='https://arxiv.org/pdf/2.pdf')], budget)
        fetch = run.tool_executions.get(tool='HTTP')
        extract = run.tool_executions.get(tool='Extractor')
        self.assertEqual((fetch.response_summary['content_type'], fetch.response_summary['final_url']), ('PDF', 'https://arxiv.org/pdf/2.pdf'))
        self.assertIn('Chaining', extract.response_summary['text_preview'])
