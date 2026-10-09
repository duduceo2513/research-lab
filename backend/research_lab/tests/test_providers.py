"""Provider unit tests. Every HTTP call is mocked — none of these touch the real internet."""
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings

def resp(status_code, **kw):
    """An httpx.Response usable with .raise_for_status() (it needs a request attached)."""
    return httpx.Response(status_code, request=httpx.Request('GET', 'https://example.com'), **kw)


from research_lab.exceptions import ProviderError, ProviderUnavailable
from research_lab.providers.search.arxiv import ArxivProvider
from research_lab.providers.search.brightdata import BrightDataSearchProvider
from research_lab.providers.search.crossref import CrossrefProvider
from research_lab.providers.search.google_books import GoogleBooksProvider
from research_lab.providers.search.openalex import OpenAlexProvider
from research_lab.providers.search.semantic_scholar import SemanticScholarProvider

ARXIV_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Retrieval-Augmented Generation for NLP</title>
    <summary>A survey of RAG methods.</summary>
    <published>2023-01-01T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2301.00001v1"/>
  </entry>
</feed>"""


class OpenAlexProviderTests(SimpleTestCase):
    def test_search_normalises_results_and_reconstructs_the_abstract(self):
        body = {'results': [{
            'id': 'https://openalex.org/W1', 'display_name': 'A RAG Paper',
            'doi': 'https://doi.org/10.1/abc', 'publication_date': '2023-05-01',
            'authorships': [{'author': {'display_name': 'Jane Doe'}}],
            'primary_location': {'source': {'display_name': 'Journal of NLP'}},
            'best_oa_location': {'pdf_url': 'https://example.com/a.pdf'},
            'open_access': {'is_oa': True}, 'cited_by_count': 12,
            'abstract_inverted_index': {'Hello': [0], 'world': [1]},
        }]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)) as get:
            results = OpenAlexProvider().search('rag', limit=5)
        self.assertEqual(get.call_args.kwargs['params']['per_page'], 5)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual((result.title, result.doi, result.abstract), ('A RAG Paper', '10.1/abc', 'Hello world'))
        self.assertEqual(result.authors, ['Jane Doe'])
        self.assertTrue(result.open_access)
        self.assertEqual(result.pdf_url, 'https://example.com/a.pdf')
        self.assertEqual(result.citation_count, 12)

    def test_http_error_becomes_provider_error(self):
        with mock.patch('httpx.get', return_value=resp(500)):
            with self.assertRaises(ProviderError):
                OpenAlexProvider().search('rag', limit=5)

    @override_settings(OPENALEX_MAILTO='me@example.com', OPENALEX_API_KEY='k')
    def test_optional_credentials_are_forwarded(self):
        with mock.patch('httpx.get', return_value=resp(200, json={'results': []})) as get:
            OpenAlexProvider().search('rag', limit=5)
        self.assertEqual(get.call_args.kwargs['params']['mailto'], 'me@example.com')
        self.assertEqual(get.call_args.kwargs['params']['api_key'], 'k')


class SemanticScholarProviderTests(SimpleTestCase):
    def test_search_normalises_results(self):
        body = {'data': [{
            'paperId': 'p1', 'title': 'RAG at Scale', 'abstract': 'We study RAG.', 'url': 'https://s2/p1',
            'year': 2022, 'authors': [{'name': 'A. Smith'}], 'venue': 'ACL', 'citationCount': 5,
            'isOpenAccess': True, 'openAccessPdf': {'url': 'https://s2/p1.pdf'},
            'externalIds': {'DOI': '10.2/xyz'}, 'publicationDate': '2022-06-15',
        }]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)):
            results = SemanticScholarProvider().search('rag', limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0].title, results[0].doi, results[0].citation_count), ('RAG at Scale', '10.2/xyz', 5))
        self.assertEqual(results[0].published_at.year, 2022)

    @override_settings(SEMANTIC_SCHOLAR_API_KEY='sk')
    def test_api_key_is_sent_as_a_header_not_a_query_param(self):
        with mock.patch('httpx.get', return_value=resp(200, json={'data': []})) as get:
            SemanticScholarProvider().search('rag', limit=5)
        self.assertEqual(get.call_args.kwargs['headers']['x-api-key'], 'sk')

    def test_provider_down(self):
        with mock.patch('httpx.get', side_effect=httpx.ConnectTimeout('timed out')):
            with self.assertRaises(ProviderError):
                SemanticScholarProvider().search('rag', limit=5)


class CrossrefProviderTests(SimpleTestCase):
    def test_search_normalises_results(self):
        body = {'message': {'items': [{
            'DOI': '10.3/doi', 'title': ['A Crossref Paper'], 'URL': 'https://doi.org/10.3/doi',
            'publisher': 'ACM', 'author': [{'given': 'Ann', 'family': 'Lee'}],
            'published-print': {'date-parts': [[2021, 3]]}, 'is-referenced-by-count': 7,
            'license': [{'URL': 'https://license'}],
        }]}}
        with mock.patch('httpx.get', return_value=resp(200, json=body)):
            results = CrossrefProvider().search('rag', limit=5)
        self.assertEqual((results[0].title, results[0].doi, results[0].authors), ('A Crossref Paper', '10.3/doi', ['Ann Lee']))
        self.assertEqual(results[0].published_at.year, 2021)
        self.assertTrue(results[0].open_access)


class ArxivProviderTests(SimpleTestCase):
    def test_search_parses_atom_xml(self):
        with mock.patch('httpx.get', return_value=resp(200, content=ARXIV_ATOM.encode())):
            results = ArxivProvider().search('rag', limit=5)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.title, 'Retrieval-Augmented Generation for NLP')
        self.assertEqual(result.authors, ['Jane Doe'])
        self.assertEqual(result.pdf_url, 'http://arxiv.org/pdf/2301.00001v1')
        self.assertTrue(result.open_access)

    def test_malformed_xml_is_a_provider_error(self):
        with mock.patch('httpx.get', return_value=resp(200, content=b'not xml')):
            with self.assertRaises(ProviderError):
                ArxivProvider().search('rag', limit=5)


class GoogleBooksProviderTests(SimpleTestCase):
    def test_search_normalises_results(self):
        body = {'items': [{
            'id': 'b1', 'volumeInfo': {
                'title': 'Deep Learning', 'authors': ['Ian Goodfellow'], 'publisher': 'MIT Press',
                'publishedDate': '2016', 'description': 'A textbook.',
                'industryIdentifiers': [{'type': 'ISBN_13', 'identifier': '9780262035613'}],
            },
            'accessInfo': {'viewability': 'ALL_PAGES'},
        }]}
        with mock.patch('httpx.get', return_value=resp(200, json=body)):
            results = GoogleBooksProvider().search('deep learning', limit=5)
        self.assertEqual((results[0].title, results[0].isbn), ('Deep Learning', '9780262035613'))
        self.assertTrue(results[0].open_access)
        self.assertEqual(results[0].published_at.year, 2016)


class BrightDataProviderTests(SimpleTestCase):
    @override_settings(BRIGHTDATA_API_TOKEN='', BRIGHTDATA_SERP_ZONE='')  # independent of a developer's .env
    def test_unconfigured_is_an_explicit_unavailable_not_an_error(self):
        with self.assertRaises(ProviderUnavailable):
            BrightDataSearchProvider().search('rag', limit=5)

    @override_settings(BRIGHTDATA_API_TOKEN='tok', BRIGHTDATA_SERP_ZONE='zone1')
    def test_search_parses_organic_results_and_sends_bearer_auth(self):
        body = {'organic': [{'link': 'https://uni.edu/rag.pdf', 'title': 'RAG course notes',
                             'description': 'Lecture notes', 'rank': 1}]}
        with mock.patch('httpx.post', return_value=resp(200, json=body)) as post:
            results = BrightDataSearchProvider().search('rag', limit=5)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer tok')
        self.assertEqual(post.call_args.kwargs['json']['zone'], 'zone1')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, 'RAG course notes')

    @override_settings(BRIGHTDATA_API_TOKEN='tok', BRIGHTDATA_SERP_ZONE='zone1')
    def test_upstream_failure_is_a_provider_error(self):
        with mock.patch('httpx.post', return_value=resp(503)):
            with self.assertRaises(ProviderError):
                BrightDataSearchProvider().search('rag', limit=5)
