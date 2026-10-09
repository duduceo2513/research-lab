"""Agent 9 (spec section 9) — Final Reviewer. Never the same agent/call that wrote the assignment.
Returns ``approved`` or ``needs_revision``; the Boss caps the generator<->reviewer loop at
``RESEARCH_LAB_MAX_REVISION_CYCLES`` (default 2) to guarantee termination.
"""
from __future__ import annotations

import logging

from llm.models import PromptCode
from research_lab.models import (AGENT_FINAL_REVIEWER, Assignment, GeneratedLecture, LectureStatus, ResearchRun,
                                 ResearchSource, ReviewStatus)
from research_lab.schemas import ReviewResult
from research_lab.services import journal, llm_json
from research_lab.services.llm_router import resolve_configuration

logger = logging.getLogger('research_lab')


def _parse_review(parsed: dict | None) -> ReviewResult:
    if not isinstance(parsed, dict):
        return ReviewResult(decision='needs_revision', score=0.0,
                           issues=['The reviewer model returned an unparsable response.'])
    decision = 'approved' if str(parsed.get('decision', '')).strip().lower() == 'approved' else 'needs_revision'
    try:
        score = max(0.0, min(100.0, float(parsed.get('score', 0))))
    except (TypeError, ValueError):
        score = 0.0
    issues = parsed.get('issues')
    return ReviewResult(decision=decision, score=score, issues=[str(i) for i in issues] if isinstance(issues, list) else [])


def _note_verdict(execution, result: ReviewResult, target: str = '') -> None:
    journal.note(execution, ('Approved' if result.decision == 'approved' else 'Needs revision')
                 + f', score {result.score:.0f}/100.', 'result')
    approved = result.decision == 'approved'
    journal.decide(execution, 'approved' if approved else 'revision_required',
                   f'{target.capitalize()}: {"APPROVED" if approved else "REVISION REQUIRED"} ({result.score:.0f}/100).',
                   reason='; '.join(result.issues[:3]) if result.issues else 'No blocking issues found.',
                   next_action='Finish.' if approved else f'Send the {target} back for revision.',
                   target=target, score=result.score, issues=result.issues[:8])
    for issue in result.issues[:8]:
        journal.note(execution, f'Issue: {issue}', 'thought')


def review(research_run: ResearchRun, sequence: int, assignment: Assignment,
          accepted_sources: list[ResearchSource]) -> tuple[int, ReviewResult]:
    config = resolve_configuration(research_run, AGENT_FINAL_REVIEWER)
    from research_lab.agents.assignment_generator import _format_sources, topic_query  # local import: avoids a cycle

    with journal.agent_step(research_run, AGENT_FINAL_REVIEWER, sequence,
                            input_summary={'assignment_id': assignment.pk, 'model': config.name}) as execution:
        journal.note(execution, f'Independently checking "{assignment.title}" against the sources with {config.name}…', 'thought')
        parsed, generation_run = llm_json.call_structured(
            question=f'Review assignment: {assignment.title}', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW,
            configuration=config,
            variables={
                'topic': research_run.topic, 'education_level': research_run.education_level,
                'sources': _format_sources(accepted_sources, topic_query(research_run)),
                'assignment': (f'Title: {assignment.title}\nObjectives: {assignment.objectives}\n'
                              f'Instructions: {assignment.instructions}\nQuestions: {assignment.questions}'),
            },
            metadata={'run_id': research_run.pk, 'agent': AGENT_FINAL_REVIEWER},
        )
        result = _parse_review(parsed)
        _note_verdict(execution, result, 'assignment')
        execution.generation_run = generation_run
        execution.output_summary = {'decision': result.decision, 'score': result.score, 'issue_count': len(result.issues)}

    assignment.review_status = ReviewStatus.APPROVED if result.decision == 'approved' else ReviewStatus.NEEDS_REVISION
    assignment.review_score = result.score
    assignment.review_issues = result.issues
    assignment.reviewer_generation_run = generation_run
    assignment.save(update_fields=['review_status', 'review_score', 'review_issues', 'reviewer_generation_run'])

    return sequence + 1, result


def _format_lecture(lecture: GeneratedLecture) -> str:
    lines = [f'Title: {lecture.title}', f'Learning objectives: {lecture.learning_objectives}']
    for section in lecture.content_json.get('sections') or []:
        lines.append(f"- {section.get('title', '')}: {section.get('content', '')[:3000]} "
                     f"(source_ids={section.get('source_ids', [])})")
        # Key points and examples (where the code lives) are part of the lecture: the reviewer must see
        # them, or it reports "no examples" for a lecture that has them.
        for label, items in (('Key points', section.get('key_points')), ('Examples', section.get('examples'))):
            if isinstance(items, list) and items:
                lines.append(f'    {label}: ' + ' | '.join(str(item)[:800] for item in items))
    if lecture.content_json.get('summary'):
        lines.append(f"Summary: {lecture.content_json['summary']}")
    return '\n'.join(lines)


def review_lecture(research_run: ResearchRun, sequence: int, lecture: GeneratedLecture,
                   accepted_sources: list[ResearchSource]) -> tuple[int, ReviewResult]:
    """Same contract as ``review()`` (above) but for a ``GeneratedLecture`` — checks topic/level
    fit, structure, factual consistency with the accepted sources, unsupported claims, and whether
    every substantive section actually carries real source grounding."""
    config = resolve_configuration(research_run, AGENT_FINAL_REVIEWER)
    from research_lab.agents.assignment_generator import _format_sources, topic_query  # local import: avoids a cycle

    with journal.agent_step(research_run, AGENT_FINAL_REVIEWER, sequence,
                            input_summary={'lecture_id': lecture.pk, 'model': config.name}) as execution:
        journal.note(execution, f'Independently checking "{lecture.title}" for accuracy, grounding and level fit with {config.name}…', 'thought')
        parsed, generation_run = llm_json.call_structured(
            question=f'Review lecture: {lecture.title}', prompt_code=PromptCode.RESEARCH_LECTURE_REVIEW,
            configuration=config,
            variables={
                'topic': research_run.topic, 'education_level': research_run.education_level,
                'sources': _format_sources(accepted_sources, f'{topic_query(research_run)} {lecture.title}'),
                'lecture': _format_lecture(lecture),
            },
            metadata={'run_id': research_run.pk, 'agent': AGENT_FINAL_REVIEWER},
        )
        result = _parse_review(parsed)
        _note_verdict(execution, result, 'lecture')
        execution.generation_run = generation_run
        execution.output_summary = {'decision': result.decision, 'score': result.score, 'issue_count': len(result.issues)}

    lecture.status = LectureStatus.APPROVED if result.decision == 'approved' else LectureStatus.NEEDS_REVISION
    lecture.review_score = result.score
    lecture.review_result = {'decision': result.decision, 'issues': result.issues}
    lecture.reviewer_generation_run = generation_run
    lecture.save(update_fields=['status', 'review_score', 'review_result', 'reviewer_generation_run'])

    return sequence + 1, result
