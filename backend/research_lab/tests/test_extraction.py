from django.test import SimpleTestCase

from research_lab.services.extraction import extract_text
from core.testing import pdf_bytes


class HtmlExtractionTests(SimpleTestCase):
    def test_boilerplate_is_stripped(self):
        html = b"""
        <html><body>
        <nav>Site navigation</nav>
        <header>Site header</header>
        <main><h1>Retrieval-Augmented Generation</h1><p>RAG combines retrieval and generation.</p></main>
        <footer>Copyright 2024</footer>
        <script>trackEverything()</script>
        </body></html>
        """
        result = extract_text(html, 'HTML')
        self.assertIn('RAG combines retrieval and generation', result.text)
        self.assertNotIn('navigation', result.text.lower())
        self.assertNotIn('trackEverything', result.text)
        self.assertNotIn('Copyright', result.text)


class PdfExtractionTests(SimpleTestCase):
    def test_reuses_the_materials_pdf_extractor(self):
        content = pdf_bytes(['Retrieval-Augmented Generation combines search and generation.'])
        result = extract_text(content, 'PDF')
        self.assertIn('Retrieval-Augmented Generation', result.text)


class UnsupportedContentTypeTests(SimpleTestCase):
    def test_raises_value_error(self):
        with self.assertRaises(ValueError):
            extract_text(b'...', 'ZIP')
