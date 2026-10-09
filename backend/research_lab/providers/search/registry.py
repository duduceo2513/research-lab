"""Provider registries used by the Web Research and Academic Research agents."""
from __future__ import annotations

from research_lab.providers.search.arxiv import ArxivProvider
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.brightdata import BrightDataSearchProvider
from research_lab.providers.search.core_ac import CoreProvider
from research_lab.providers.search.crossref import CrossrefProvider
from research_lab.providers.search.google_books import GoogleBooksProvider
from research_lab.providers.search.open_library import OpenLibraryProvider
from research_lab.providers.search.openalex import OpenAlexProvider
from research_lab.providers.search.semantic_scholar import SemanticScholarProvider
from research_lab.providers.search.wikipedia import WikipediaProvider
from research_lab.providers.search.youtube import YouTubeProvider

WEB_PROVIDERS: list[SearchProvider] = [BrightDataSearchProvider(), WikipediaProvider(), YouTubeProvider()]

ACADEMIC_PROVIDERS: list[SearchProvider] = [
    OpenAlexProvider(), CoreProvider(), SemanticScholarProvider(), CrossrefProvider(), ArxivProvider(),
    GoogleBooksProvider(), OpenLibraryProvider(),
]
