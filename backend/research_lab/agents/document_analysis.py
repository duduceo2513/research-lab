"""Agent 5 — Document Analysis. Search and analysis are deliberately separate stages (per spec):
this agent takes the documents that Document Retrieval stored (``ResearchDocument`` with status
``FETCHED`` and the original on disk), extracts their plain text and removes content duplicates —
the same document reachable under two URLs. It does not decide whether a source is *good*, only what
it *contains*; that judgement belongs to the Source Validator.

One tool: the text extractor (PDF / PPTX / DOCX / HTML / TXT parsers). Sources that were never
downloaded (description-only providers, failed or skipped downloads) pass through unchanged — they
already carry whatever text the API provided.
"""
from __future__ import annotations

import logging

from research_lab.models import AGENT_DOCUMENT_ANALYSIS, DocumentStatus, ResearchDocument, ResearchRun, ResearchSource
from research_lab.services import dedup, extraction, journal
from research_lab.services.resilience import Budget

logger = logging.getLogger('research_lab')


def run(research_run: ResearchRun, sequence: int, sources: list[ResearchSource],
        budget: Budget) -> tuple[int, list[ResearchSource]]:
    """Returns ``(next_sequence, non-duplicate sources)``."""
    to_extract = [s for s in sources if getattr(s, 'document', None) and s.document.status == DocumentStatus.FETCHED
                  and s.document.file]

    with journal.agent_step(
        research_run, AGENT_DOCUMENT_ANALYSIS, sequence,
        input_summary={'sources': len(sources), 'to_extract': len(to_extract)},
    ) as execution:
        journal.note(execution, f'Reading {len(to_extract)} downloaded documents '
                                f'({len(sources) - len(to_extract)} sources have only a description).', 'thought')
        seen_content_hashes: dict[str, int] = {}
        content_duplicates = 0
        total = len(to_extract)

        def report(done: int, current: str = '') -> None:
            journal.progress(execution, [
                {'id': 'extract', 'label': 'Extract text', 'status': 'active' if done < total else 'done',
                 'detail': f'{done} / {total}'},
                {'id': 'content_dedup', 'label': 'Content dedup', 'status': 'done' if done >= total else 'pending',
                 'detail': f'{content_duplicates} found'},
            ], processed=done, total=total, current_item=current)

        report(0)
        for index, source in enumerate(to_extract, start=1):
            budget.check(cancel_requested=_refresh_cancel_flag(research_run))
            document = ResearchDocument.objects.get(pk=source.document.pk)
            label = f'[{index}/{total}] {source.title[:80]}'
            report(index - 1, source.title[:140])
            journal.tool_start(execution, 'Extractor', 'parse', content_type=document.content_type)
            try:
                with document.file.open('rb') as handle:
                    content = handle.read()
                extracted = extraction.extract_text(content, document.content_type)
            except Exception as exc:  # a malformed PDF/DOCX or a missing file must not abort the whole run
                journal.note(execution, f'{label}: text extraction failed ({exc}).', 'warn')
                logger.warning('Extraction failed for source %s: %s', source.pk, exc)
                journal.log_tool(research_run, execution, 'Extractor', status='FAILED', operation='parse',
                                 request_summary={'file': document.file_name, 'content_type': document.content_type},
                                 error_message=f'{type(exc).__name__}: {exc}'[:500])
                document.status = DocumentStatus.FAILED
                document.error_message = f'{type(exc).__name__}: {exc}'[:2000]
                document.save(update_fields=['status', 'error_message', 'updated_at'])
                continue

            # The API's own full text (kept by Retrieval) wins when it is longer than what was extracted.
            text = extracted.text if len(extracted.text) >= len(document.text) else document.text
            digest = dedup.content_hash(text) if text else ''
            if digest:
                if digest in seen_content_hashes:
                    source.is_duplicate = True
                    source.duplicate_of_id = seen_content_hashes[digest]
                    content_duplicates += 1
                    journal.note(execution, f'{label}: same content as an earlier source, marked duplicate.', 'thought')
                else:
                    seen_content_hashes[digest] = source.pk
                source.content_hash = digest
                source.save(update_fields=['content_hash', 'is_duplicate', 'duplicate_of'])

            document.status = DocumentStatus.EXTRACTED if text else DocumentStatus.FETCHED
            document.text, document.text_length = text, len(text)
            document.extract_latency_ms = extracted.latency_ms
            document.error_message = '' if text else 'The document contains no extractable text (a scan?).'
            document.save()
            journal.note(execution, f'{label}: extracted {len(text):,} characters.', 'result')
            journal.log_tool(research_run, execution, 'Extractor', status='SUCCESS', operation='parse',
                             request_summary={'file': document.file_name, 'content_type': document.content_type},
                             response_summary={'chars': len(text), 'content_type': document.content_type,
                                               'text_preview': text[:600] + ('…' if len(text) > 600 else '')},
                             latency_ms=extracted.latency_ms)
            report(index)

        report(total)
        execution.output_summary = {
            'analyzed': len(sources), 'extracted': len(to_extract), 'content_duplicates': content_duplicates,
        }
        unique = len(sources) - content_duplicates
        journal.decide(execution, 'handoff', f'{unique} unique documents ready.',
                       reason=f'{content_duplicates} content duplicates were dropped.',
                       next_action='Finish: the materials are ready to read.' if research_run.mode == 'SEARCH'
                       else 'Pass the documents to the Source Validator.',
                       analyzed=len(sources), content_duplicates=content_duplicates)

    return sequence + 1, [s for s in sources if not s.is_duplicate]


def _refresh_cancel_flag(research_run: ResearchRun) -> bool:
    research_run.refresh_from_db(fields=['cancel_requested'])
    return research_run.cancel_requested
