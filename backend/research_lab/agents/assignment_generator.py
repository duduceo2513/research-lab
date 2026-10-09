"""Agent 8 (spec section 8) — Assignment Generator. Writes the assignment from ACCEPTED sources
only. Also handles revisions (spec section 9's reviewer loop) by reusing the same LLM call with a
different prompt (``RESEARCH_ASSIGNMENT_REVISION``) that includes the previous draft + reviewer
feedback — the generator never reviews its own output, that is always a separate agent/call.

When the run also built a (reviewed) lecture, that lecture's content is passed in too, so the
assignment matches what was actually taught rather than just the raw source list.
"""
from __future__ import annotations

import logging

from django.conf import settings

from llm.models import PromptCode
from research_lab.models import AGENT_ASSIGNMENT_GENERATOR, Assignment, GeneratedLecture, ResearchRun, ResearchSource
from research_lab.services import journal, llm_json, passages
from research_lab.services.llm_router import resolve_configuration

logger = logging.getLogger('research_lab')


def topic_query(research_run: ResearchRun) -> str:
    """What the passages of a long source are ranked against."""
    return f'{research_run.topic} {research_run.description}'.strip()


def _format_sources(sources: list[ResearchSource], query: str = '') -> str:
    """The numbered source list handed to a writer/reviewer: for each source its citation line plus the
    passages of its full text that best match ``query`` (``services/passages.py``) — a 200-page book
    contributes its relevant chapter, never its whole text. The total stays within
    ``RESEARCH_LAB_CONTEXT_CHARS``."""
    per_source = max(settings.RESEARCH_LAB_CONTEXT_CHARS // max(len(sources), 1), 1500)
    lines = []
    for i, source in enumerate(sources, start=1):
        authors = ', '.join(source.authors[:3]) or 'Unknown author'
        year = source.published_at.year if source.published_at else 'n.d.'
        document = getattr(source, 'document', None)
        text = (document.text if document and document.text else source.abstract) or ''
        excerpt = passages.select_context(text, query or source.title, per_source)
        lines.append(f'[{i}] (id={source.pk}) {source.title} — {authors} ({year}).\n{excerpt}')
    return '\n\n'.join(lines)


def _blank_draft(reason: str) -> dict:
    return {'title': 'Assignment could not be generated', 'objectives': [], 'instructions': reason,
           'questions': [], 'grading_criteria': '', 'references': [], 'answer_key': ''}


def generate(research_run: ResearchRun, sequence: int, accepted_sources: list[ResearchSource],
            *, previous_draft: dict | None = None, feedback: list[str] | None = None,
            lecture: GeneratedLecture | None = None) -> tuple[int, Assignment]:
    config = resolve_configuration(research_run, AGENT_ASSIGNMENT_GENERATOR)
    is_revision = previous_draft is not None

    with journal.agent_step(
        research_run, AGENT_ASSIGNMENT_GENERATOR, sequence,
        input_summary={'accepted_sources': len(accepted_sources), 'revision': is_revision,
                       'lecture_id': lecture.pk if lecture else None, 'model': config.name},
    ) as execution:
        if is_revision:
            journal.note(execution, 'Revising the assignment after reviewer feedback: ' + '; '.join(feedback or [])[:400], 'thought')
        else:
            journal.note(execution, f'Designing a {research_run.difficulty.lower()} {research_run.assignment_type.lower()} '
                                    f'assignment from {len(accepted_sources)} approved sources'
                                    + (' and the generated lecture.' if lecture else '.'), 'thought')
        def stages(active: str, detail: dict | None = None) -> None:
            order = [('sources', 'Collect approved sources'), ('write', 'Write tasks, rubric and references'),
                     ('save', 'Save assignment')]
            reached = [key for key, _ in order].index(active) if active != 'done' else len(order)
            journal.progress(execution, [
                {'id': key, 'label': label, 'status': 'done' if i < reached else 'active' if i == reached else 'pending',
                 **({'detail': (detail or {}).get(key)} if (detail or {}).get(key) else {})}
                for i, (key, label) in enumerate(order)
            ], approved_sources=len(accepted_sources), lecture_version_used=(lecture.version if lecture else None),
                assignment_version=research_run.revision_count + 1, revision=is_revision)

        stages('sources', {'sources': f'{len(accepted_sources)} sources'})
        if not accepted_sources:
            journal.note(execution, 'No approved sources, so no grounded assignment can be built.', 'warn')
            draft = _blank_draft('No sources passed validation, so no assignment could be generated '
                                 'from vetted material.')
            execution.output_summary = {'skipped': True, 'reason': 'no_accepted_sources'}
            generation_run = None
        else:
            variables = {
                'topic': research_run.topic, 'education_level': research_run.education_level,
                'assignment_type': research_run.assignment_type, 'difficulty': research_run.difficulty,
                'sources': _format_sources(accepted_sources, topic_query(research_run)),
                'lecture': lecture.plain_text if lecture else '',
            }
            if is_revision:
                variables['previous_draft'] = str(previous_draft)
                variables['feedback'] = '\n'.join(f'- {issue}' for issue in (feedback or []))
                prompt_code = PromptCode.RESEARCH_ASSIGNMENT_REVISION
            else:
                prompt_code = PromptCode.RESEARCH_ASSIGNMENT_GENERATION

            journal.note(execution, f'Writing with {config.name}…')
            stages('write')
            parsed, generation_run = llm_json.call_structured(
                question=f'Generate assignment: {research_run.topic}', prompt_code=prompt_code,
                configuration=config, variables=variables,
                metadata={'run_id': research_run.pk, 'agent': AGENT_ASSIGNMENT_GENERATOR},
            )
            draft = parsed if isinstance(parsed, dict) else _blank_draft(
                'The assignment-generation model returned an unparsable response.')
            execution.generation_run = generation_run
            journal.note(execution, f'Drafted "{draft.get("title", "")}" with {len(draft.get("questions") or [])} questions.', 'result')
            execution.output_summary = {'title': draft.get('title', ''), 'question_count': len(draft.get('questions', []))}

        stages('save', {'write': f"{len(draft.get('questions') or [])} questions"})
        assignment, _created = Assignment.objects.update_or_create(run=research_run, defaults={
            'title': str(draft.get('title', ''))[:500],
            'objectives': draft.get('objectives') if isinstance(draft.get('objectives'), list) else [],
            'instructions': str(draft.get('instructions', '')),
            'questions': draft.get('questions') if isinstance(draft.get('questions'), list) else [],
            'grading_criteria': str(draft.get('grading_criteria', '')),
            'references': draft.get('references') if isinstance(draft.get('references'), list) else [],
            'answer_key': str(draft.get('answer_key', '')),
            'assignment_type': research_run.assignment_type, 'difficulty': research_run.difficulty,
            'generation_run': generation_run if not is_revision else None,
            'metadata': {'revision_of_run': research_run.pk} if is_revision else {},
        })

        stages('done', {'write': f"{len(assignment.questions)} questions"})
        journal.decide(execution, 'drafted', f'Assignment v{research_run.revision_count + 1}: {len(assignment.questions)} questions.',
                       reason='Built only from approved sources' + (f' and lecture v{lecture.version}.' if lecture else '.'),
                       next_action='Send the assignment to the Final Reviewer.',
                       assignment_version=research_run.revision_count + 1, questions=len(assignment.questions))

    return sequence + 1, assignment
