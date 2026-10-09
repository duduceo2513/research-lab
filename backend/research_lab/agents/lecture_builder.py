"""Agent 6 — Lecture Builder. Builds one complete lecture from ONLY source-validator-APPROVED
(ACCEPT-decision) sources — never rejected ones, and never a fact the sources don't support (see
the ``insufficient_sources`` escape hatch below, and the source_ids grounding filter in
``generate()``).

Like the Assignment Generator, revisions reuse this same function with a different prompt
(``RESEARCH_LECTURE_REVISION``) carrying the previous draft + reviewer feedback — the builder
never reviews its own output, that's always ``agents.final_reviewer.review_lecture``.
"""
from __future__ import annotations

import logging

from llm.models import PromptCode
from research_lab.models import AGENT_LECTURE_BUILDER, GeneratedLecture, LectureStatus, ResearchRun, ResearchSource
from research_lab.services import journal, llm_json
from research_lab.services.lecture_format import render_plain_text
from research_lab.services.llm_router import resolve_configuration

logger = logging.getLogger('research_lab')


def _blank_draft(reason: str) -> dict:
    return {'title': '', 'learning_objectives': [], 'sections': [], 'summary': '',
           'self_check_questions': [], 'references': [], 'status': 'insufficient_sources',
           'missing_topics': [reason]}


def resolve_source_id(value, accepted_sources: list[ResearchSource]) -> int | None:
    """Maps whatever number the model cited to a real source primary key, or ``None``.

    The sources are listed as ``[3] (id=275) Title`` and the prompt says "source [3] -> 3", so models
    cite the list *position* (1..N) as often as the database id. Both are accepted; a number that is
    neither is dropped (no invented references).
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        number = int(str(value).strip().strip('[]'))
    except ValueError:
        return None
    if 1 <= number <= len(accepted_sources):
        return accepted_sources[number - 1].pk
    return number if number in {source.pk for source in accepted_sources} else None


def _next_version(research_run: ResearchRun) -> int:
    latest = GeneratedLecture.objects.filter(run=research_run).order_by('-version').values_list(
        'version', flat=True).first()
    return (latest or 0) + 1


def generate(research_run: ResearchRun, sequence: int, accepted_sources: list[ResearchSource],
            *, previous_draft: dict | None = None, feedback: list[str] | None = None) -> tuple[int, GeneratedLecture]:
    from research_lab.agents.assignment_generator import _format_sources, topic_query  # local import: avoids a cycle

    config = resolve_configuration(research_run, AGENT_LECTURE_BUILDER)
    is_revision = previous_draft is not None

    with journal.agent_step(
        research_run, AGENT_LECTURE_BUILDER, sequence,
        input_summary={'accepted_sources': len(accepted_sources), 'revision': is_revision, 'model': config.name},
    ) as execution:
        if is_revision:
            journal.note(execution, 'Revising the lecture after reviewer feedback: ' + '; '.join(feedback or [])[:400], 'thought')
        else:
            journal.note(execution, f'Planning a {research_run.lecture_target_duration_minutes}-minute '
                                    f'{research_run.lecture_detail_level.lower()}-detail lecture from '
                                    f'{len(accepted_sources)} approved sources.', 'thought')
        def stages(active: str, detail: dict | None = None) -> None:
            order = [('sources', 'Collect approved sources'), ('write', 'Write lecture'),
                     ('ground', 'Verify source references'), ('save', 'Render and save')]
            reached = [key for key, _ in order].index(active) if active != 'done' else len(order)
            journal.progress(execution, [
                {'id': key, 'label': label, 'status': 'done' if i < reached else 'active' if i == reached else 'pending',
                 **({'detail': (detail or {}).get(key)} if (detail or {}).get(key) else {})}
                for i, (key, label) in enumerate(order)
            ], approved_sources=len(accepted_sources), revision=is_revision,
                version_in_progress=_next_version(research_run))

        stages('sources', {'sources': f'{len(accepted_sources)} sources'})
        if not accepted_sources:
            journal.note(execution, 'No approved sources, so no grounded lecture can be built.', 'warn')
            draft = _blank_draft('No sources passed validation, so no lecture could be built from vetted material.')
            execution.output_summary = {'skipped': True, 'reason': 'no_accepted_sources'}
            generation_run = None
        else:
            variables = {
                'topic': research_run.topic, 'education_level': research_run.education_level,
                'language': research_run.language,
                'target_duration_minutes': research_run.lecture_target_duration_minutes,
                'detail_level': research_run.lecture_detail_level,
                'include_examples': research_run.lecture_include_examples,
                'include_summary': research_run.lecture_include_summary,
                'sources': _format_sources(accepted_sources, topic_query(research_run)),
            }
            if is_revision:
                variables['previous_draft'] = str(previous_draft)
                variables['feedback'] = '\n'.join(f'- {issue}' for issue in (feedback or []))
                prompt_code = PromptCode.RESEARCH_LECTURE_REVISION
            else:
                prompt_code = PromptCode.RESEARCH_LECTURE_GENERATION

            journal.note(execution, f'Writing with {config.name}…')
            stages('write', {'sources': f'{len(accepted_sources)} sources'})
            parsed, generation_run = llm_json.call_structured(
                question=f'Build lecture: {research_run.topic}', prompt_code=prompt_code,
                configuration=config, variables=variables,
                metadata={'run_id': research_run.pk, 'agent': AGENT_LECTURE_BUILDER},
            )
            draft = parsed if isinstance(parsed, dict) else _blank_draft(
                'The lecture-building model returned an unparsable response.')
            execution.generation_run = generation_run
            titles = [str(s.get('title', '')) for s in (draft.get('sections') or []) if isinstance(s, dict)]
            if titles:
                journal.note(execution, f'Drafted "{draft.get("title", "")}" with {len(titles)} sections: '
                                        + ' | '.join(titles), 'result')
            if draft.get('missing_topics'):
                journal.note(execution, 'Not covered by the sources: ' + '; '.join(map(str, draft['missing_topics'])), 'warn')
            execution.output_summary = {'title': draft.get('title', ''), 'section_count': len(draft.get('sections', []) or [])}

        # Grounding must be real: drop any source_id the model mentioned that isn't actually one
        # of this run's accepted sources, rather than trust it (spec: "Нельзя создавать фиктивные
        # ссылки или references").
        stages('ground', {'write': f"{len(draft.get('sections') or [])} sections"})
        sections = draft.get('sections') if isinstance(draft.get('sections'), list) else []
        for section in sections:
            if isinstance(section, dict) and isinstance(section.get('source_ids'), list):
                resolved = (resolve_source_id(sid, accepted_sources) for sid in section['source_ids'])
                section['source_ids'] = list(dict.fromkeys(sid for sid in resolved if sid is not None))
        references = draft.get('references') if isinstance(draft.get('references'), list) else []
        for reference in references:
            if isinstance(reference, dict) and 'source_id' in reference:
                reference['source_id'] = resolve_source_id(reference['source_id'], accepted_sources)
        draft['references'] = [r for r in references if not isinstance(r, dict) or r.get('source_id') is not None]

        declared_insufficient = str(draft.get('status', '')).strip().lower() == 'insufficient_sources'
        status = LectureStatus.INSUFFICIENT_SOURCES if (declared_insufficient or not sections) else LectureStatus.DRAFT

        content = {
            'sections': sections,
            'self_check_questions': draft.get('self_check_questions') if isinstance(draft.get('self_check_questions'), list) else [],
            'references': draft.get('references') if isinstance(draft.get('references'), list) else [],
            'missing_topics': draft.get('missing_topics') if isinstance(draft.get('missing_topics'), list) else [],
            'summary': str(draft.get('summary', '')),
        }
        title = str(draft.get('title', ''))[:500]
        learning_objectives = draft.get('learning_objectives') if isinstance(draft.get('learning_objectives'), list) else []

        stages('save')
        lecture = GeneratedLecture.objects.create(
            run=research_run, version=_next_version(research_run), title=title,
            learning_objectives=learning_objectives, content_json=content,
            plain_text=render_plain_text(title=title, learning_objectives=learning_objectives, content=content),
            status=status, generation_run=generation_run,
        )

        stages('done', {'write': f'{len(sections)} sections'})
        journal.decide(execution, 'insufficient_sources' if status == LectureStatus.INSUFFICIENT_SOURCES else 'drafted',
                       f'Lecture v{lecture.version}: {len(sections)} sections.' if sections
                       else 'No lecture could be built from the approved sources.',
                       reason=('Built only from approved sources; unsupported source ids were dropped.' if sections
                               else 'Too little validated material.'),
                       next_action='Send the lecture to the Final Reviewer.' if sections else 'Skip lecture review.',
                       lecture_version=lecture.version, sections=len(sections))

    return sequence + 1, lecture
