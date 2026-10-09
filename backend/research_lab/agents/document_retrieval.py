"""Agent 4 — Document Retrieval. Takes the raw candidates found by Web/Academic Research,
removes duplicates by metadata, records each survivor as a ``ResearchSource`` and downloads its
original document. One job, one tool (the SSRF-safe HTTP fetcher with its fallback chain): it does
not read the documents — turning bytes into text is the next agent's job (``document_analysis``).

The hand-off between the two agents is explicit state, not memory: every downloaded original is
stored on ``ResearchDocument.file`` with status ``FETCHED``; Document Analysis reads it from there.

Download policy (mirrors the verified ``web_search_apis`` script):

* sources that only *describe* a resource (Crossref, Google Books, Open Library, YouTube) are never
  downloaded — their description is the text;
* a result that already carries full text (CORE) keeps it even if the download fails;
* at most ``RESEARCH_LAB_FETCH_PER_PROVIDER`` downloads are attempted per source in one run, the
  remaining results are still listed with the text the API gave us;
* access is never forced: HTTP 401/402/403/451 end the attempt (see ``services/fetcher.py``).
"""
from __future__ import annotations

import logging
import mimetypes
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.text import slugify

from research_lab.exceptions import FetchError
from research_lab.models import (AGENT_DOCUMENT_RETRIEVAL, DocumentStatus, FetchMethod, ResearchDocument, ResearchRun,
                                 ResearchSource, RunMode)
from research_lab.providers.search import registry
from research_lab.schemas import SourceCandidate
from research_lab.services import dedup, journal
from research_lab.services.fetcher import fetch_url
from research_lab.services.resilience import Budget

logger = logging.getLogger('research_lab')

#: File extension kept for each downloaded format (every original is stored, HTML included).
STORED_FORMATS = {'PDF': '.pdf', 'PPTX': '.pptx', 'DOCX': '.docx', 'TXT': '.txt', 'HTML': '.html'}


def _fallback_external_id(candidate: SourceCandidate) -> str:
    """Some providers (or hand-entered metadata) have no stable id — fall back to a content hash
    of title+url so the (run, provider, external_id) uniqueness constraint still dedupes retries."""
    return dedup.content_hash(f'{candidate.title}|{candidate.url}')[:64]


def persist_candidates(research_run: ResearchRun,
                       candidates: list[SourceCandidate]) -> list[tuple[ResearchSource, SourceCandidate]]:
    pairs = []
    for candidate in candidates:
        external_id = candidate.external_id or _fallback_external_id(candidate)
        source, _ = ResearchSource.objects.get_or_create(
            run=research_run, provider=candidate.provider, external_id=external_id,
            defaults={
                'source_type': candidate.source_type, 'title': candidate.title[:1000], 'url': candidate.url,
                'authors': candidate.authors, 'publisher': candidate.publisher,
                'published_at': candidate.published_at, 'doi': candidate.doi, 'isbn': candidate.isbn,
                'abstract': candidate.abstract, 'citation_count': candidate.citation_count,
                'open_access': candidate.open_access, 'pdf_url': candidate.pdf_url,
                'metadata': candidate.metadata,
            },
        )
        pairs.append((source, candidate))
    return pairs


def _metadata_only(code: str) -> bool:
    providers = [*registry.WEB_PROVIDERS, *registry.ACADEMIC_PROVIDERS]
    return any(str(p.code) == str(code) and getattr(p, 'metadata_only', False) for p in providers)


def _file_name(source: ResearchSource, url: str, content_type: str) -> str:
    stem = unquote(urlparse(url).path.rsplit('/', 1)[-1]).rsplit('.', 1)[0]
    stem = slugify(stem) or slugify(source.title) or f'source-{source.pk}'
    return f'{stem[:80]}{STORED_FORMATS[content_type]}'


def _store_text_only(source: ResearchSource, candidate: SourceCandidate, *, status: str, note: str = '') -> None:
    text = candidate.full_text or source.abstract
    ResearchDocument.objects.update_or_create(source=source, defaults={
        'status': status, 'fetch_method': FetchMethod.NONE, 'text': text, 'text_length': len(text),
        'error_message': note,
    })


def run(research_run: ResearchRun, sequence: int, candidates: list[SourceCandidate],
        budget: Budget) -> tuple[int, list[ResearchSource]]:
    """Returns ``(next_sequence, sources)`` — every persisted source, each with a ``ResearchDocument``
    (``FETCHED`` with its original on disk, or ``SKIPPED``/``FAILED`` with whatever text the API gave)."""
    unique_candidates = dedup.dedupe_candidates(candidates)
    search_mode = research_run.mode == RunMode.SEARCH
    # A full research run keeps the document budget small (an LLM reads each one); a plain search
    # lists everything it found and only limits how many documents are *downloaded* per source.
    capped = unique_candidates if search_mode else unique_candidates[:settings.RESEARCH_LAB_MAX_DOCUMENTS]
    per_provider_limit = settings.RESEARCH_LAB_FETCH_PER_PROVIDER
    attempts: dict[str, int] = {}

    with journal.agent_step(
        research_run, AGENT_DOCUMENT_RETRIEVAL, sequence,
        input_summary={'found': len(candidates), 'unique': len(unique_candidates), 'to_retrieve': len(capped)},
    ) as execution:
        journal.note(execution, f'Received {len(candidates)} candidates; '
                                f'{len(candidates) - len(unique_candidates)} metadata duplicates removed.', 'thought')
        if len(unique_candidates) > len(capped):
            journal.note(execution, f'Keeping {len(capped)} of {len(unique_candidates)} to stay within the document budget.', 'thought')
        pairs = persist_candidates(research_run, capped)
        sources = [source for source, _ in pairs]
        total = len(sources)

        def report(done: int, current: str = '') -> None:
            journal.progress(execution, [
                {'id': 'dedup', 'label': 'Remove duplicates', 'status': 'done',
                 'detail': f'{len(candidates) - len(unique_candidates)} removed'},
                {'id': 'download', 'label': 'Download originals', 'status': 'active' if done < total else 'done',
                 'detail': f'{done} / {total}'},
            ], processed=done, total=total, unique=len(unique_candidates), current_item=current)

        report(0)
        downloaded = 0
        for index, (source, candidate) in enumerate(pairs, start=1):
            budget.check(cancel_requested=_refresh_cancel_flag(research_run))
            label = f'[{index}/{total}] {source.title[:80]}'
            fetch_target = source.pdf_url or source.url
            provider = str(source.provider)

            if _metadata_only(provider):
                _store_text_only(source, candidate, status=DocumentStatus.SKIPPED)
                continue
            if not fetch_target:
                journal.note(execution, f'{label}: no link to download, using the description only.', 'warn')
                _store_text_only(source, candidate, status=DocumentStatus.SKIPPED)
                continue
            if attempts.get(provider, 0) >= per_provider_limit:
                _store_text_only(source, candidate, status=DocumentStatus.SKIPPED,
                                 note=f'Not downloaded: limit of {per_provider_limit} downloads per source reached.')
                continue
            attempts[provider] = attempts.get(provider, 0) + 1
            budget.step()

            journal.note(execution, f'{label}: downloading…')
            report(index - 1, source.title[:140])
            journal.tool_start(execution, 'HTTP', 'fetch', url=fetch_target)
            try:
                fetched = fetch_url(fetch_target)
            except FetchError as exc:
                journal.note(execution, f'{label}: download failed ({exc}).', 'warn')
                journal.log_tool(research_run, execution, 'HTTP', status='FAILED', operation='fetch',
                                 request_summary={'url': fetch_target}, error_message=str(exc))
                text = candidate.full_text or source.abstract
                ResearchDocument.objects.update_or_create(source=source, defaults={
                    'status': DocumentStatus.FAILED, 'error_message': str(exc)[:2000],
                    'text': text, 'text_length': len(text)})
                continue
            journal.log_tool(research_run, execution, fetched.fetch_method, status='SUCCESS', operation='fetch',
                             request_summary={'url': fetch_target},
                             response_summary={'bytes': len(fetched.content), 'content_type': fetched.content_type,
                                               'final_url': fetched.final_url, 'method': fetched.fetch_method},
                             latency_ms=fetched.latency_ms)

            document, _ = ResearchDocument.objects.get_or_create(source=source)
            document.status = DocumentStatus.FETCHED
            document.fetch_method, document.content_type = fetched.fetch_method, fetched.content_type
            document.fetch_latency_ms = fetched.latency_ms
            document.text, document.text_length = candidate.full_text, len(candidate.full_text)  # API text, if any
            document.error_message = ''
            name = _file_name(source, fetched.final_url, fetched.content_type)
            document.file.save(f'{source.pk}-{name}', ContentFile(fetched.content), save=False)
            document.file_name = name
            document.mime_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            document.file_size = len(fetched.content)
            document.save()
            downloaded += 1
            journal.note(execution, f'{label}: saved {len(fetched.content) // 1024} KB {fetched.content_type} '
                                    f'via {fetched.fetch_method}.', 'result')
            report(index)

        report(total)
        execution.output_summary = {
            'found': len(candidates), 'unique_after_metadata_dedup': len(unique_candidates),
            'retrieved': len(sources), 'files_saved': downloaded,
        }
        journal.decide(execution, 'handoff', f'{downloaded} documents downloaded, {len(sources) - downloaded} kept as descriptions.',
                       reason=f'{len(candidates) - len(unique_candidates)} metadata duplicates were dropped; '
                              f'at most {per_provider_limit} downloads per source.',
                       next_action='Pass the documents to Document Analysis for text extraction.',
                       retrieved=len(sources), downloaded=downloaded)
    return sequence + 1, sources


def _refresh_cancel_flag(research_run: ResearchRun) -> bool:
    research_run.refresh_from_db(fields=['cancel_requested'])
    return research_run.cancel_requested
