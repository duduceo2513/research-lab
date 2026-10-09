"""Agent 1 — Boss / Orchestrator. The only agent that decides *what runs next*; it never searches,
analyzes, validates or writes content itself (that would blur the separation the other six agents
exist for).

The routing itself is a deterministic state machine, not an LLM call: the pipeline's shape (plan ->
search -> analyze -> validate -> generate <-> review) is fixed by the feature, so an LLM decision
here would add latency, cost and a new failure mode for zero benefit. A structured
``BossDecision`` is still logged at every step (see ``schemas.BossDecision``) so the "boss decided
X because Y" observability the spec asks for exists — it is just produced by code, not a model.

``run_workflow`` is the single entry point (``research_lab.tasks.run_research_task``, run in a
background thread) and never raises: every outcome — including a crash — is persisted as a terminal
``ResearchRun.status`` before returning.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from research_lab.agents import (academic_research, assignment_generator, document_analysis, document_retrieval, final_reviewer,
                                 lecture_builder, source_validator, web_research)
from research_lab.exceptions import BudgetExceeded, RunCancelled
from research_lab.models import (AGENT_ACADEMIC_RESEARCH, AGENT_ASSIGNMENT_GENERATOR, AGENT_BOSS,
                                 AGENT_DOCUMENT_ANALYSIS, AGENT_DOCUMENT_RETRIEVAL, AGENT_FINAL_REVIEWER, AGENT_LECTURE_BUILDER,
                                 AGENT_SOURCE_VALIDATOR, AGENT_WEB_RESEARCH, LectureStatus, MaterialType,
                                 ResearchRun, ResearchRunStatus, ReviewStatus, RunMode)
from research_lab.schemas import BossDecision
from research_lab.services import events, journal
from research_lab.services.resilience import Budget

logger = logging.getLogger('research_lab')

ACADEMIC_MATERIAL_TYPES = (MaterialType.PAPERS, MaterialType.BOOKS, MaterialType.DOCUMENTATION)


def _wants(run: ResearchRun, *types: str) -> bool:
    """No material types selected means "search everything"."""
    return not run.material_types or any(t in run.material_types for t in types)


def _max_steps() -> int:
    # plan + web + academic + analysis + (one budget.step() per analyzed document) + validator +
    # lecture*lecture_revisions + generate + review*cycles, plus headroom.
    downloads = max(settings.RESEARCH_LAB_MAX_DOCUMENTS, settings.RESEARCH_LAB_FETCH_PER_PROVIDER * 12)
    return (10 + downloads + settings.RESEARCH_LAB_MAX_REVISION_CYCLES * 2
           + settings.RESEARCH_LAB_MAX_LECTURE_REVISIONS * 2)


def _set_status(run: ResearchRun, status: str, step: str) -> None:
    run.status = status
    run.current_step = step
    # started_at is set once by the workflow's first step; saving it here makes sure it is persisted.
    run.save(update_fields=['status', 'current_step', 'updated_at', 'started_at'])
    events.emit(run, events.RUN_STATUS, AGENT_BOSS, status=status.lower(), summary=step or status,
                run_status=status, current_step=step)


def _check(run: ResearchRun, budget: Budget) -> None:
    run.refresh_from_db(fields=['cancel_requested'])
    budget.check(cancel_requested=run.cancel_requested)
    budget.step()


def _execute(run_id: int) -> tuple[ResearchRun, bool, bool]:
    """Returns (run, degraded, ran). ``ran`` is False for a duplicate dispatch or a stale
    task for a run that has already reached a terminal status — ``run_workflow`` must leave such a
    run exactly as it is, not recompute and overwrite its (already-final) status. ``degraded``
    means an unexpected agent-level crash occurred but the run still produced a usable (if
    incomplete) result — see ``run_workflow`` for how that maps to the final status."""
    run = ResearchRun.objects.select_related('user').get(pk=run_id)
    if run.status != ResearchRunStatus.PENDING:
        return run, False, False

    run.started_at = timezone.now()
    _set_status(run, ResearchRunStatus.PLANNING, 'Planning')
    budget = Budget.start(max_steps=_max_steps(), max_runtime_seconds=settings.RESEARCH_LAB_MAX_RUNTIME_SECONDS)
    sequence = 1
    degraded = False
    #: Short, user-facing notes about any stage that crashed — joined into run.error_message at the
    #: end, so a PARTIAL run says *why* without having to open the Agent Logs tab. The full
    #: traceback always goes to the logger and to that stage's own AgentExecution.error_message.
    issues: list[str] = []

    with journal.agent_step(run, AGENT_BOSS, sequence, input_summary={
        'material_types': run.material_types, 'generate_assignment': run.generate_assignment,
        'generate_lecture': run.generate_lecture, 'llm_mode': run.llm_mode,
    }) as execution:
        plan = BossDecision(action='continue', next_agent='web_research,academic_research',
                            reason='Starting search across the selected material types.')
        execution.output_summary = {'plan': plan.__dict__}
        wants_web, wants_academic = _wants(run, MaterialType.WEB), _wants(run, *ACADEMIC_MATERIAL_TYPES)
        journal.note(execution, f'Taking on "{run.topic}" ({run.education_level.lower()} level).')
        journal.note(execution, 'Plan: ' + ' -> '.join(filter(None, [
            'Web Research' if wants_web else '', 'Academic Research' if wants_academic else '',
            'Document Retrieval', 'Document Analysis', 'Source Validator' if run.mode != RunMode.SEARCH else '',
            'Lecture Builder' if run.generate_lecture else '',
            'Assignment Generator' if run.generate_assignment else '',
            'Final Reviewer' if (run.generate_lecture or run.generate_assignment) else '',
        ])), 'thought')
        journal.note(execution, f'Budget: {_max_steps()} steps, {settings.RESEARCH_LAB_MAX_RUNTIME_SECONDS}s max; '
                                f'at most {settings.RESEARCH_LAB_MAX_REVISION_CYCLES} reviewer revisions.')
        first = [name for name, wanted in (('Web Research', wants_web), ('Academic Research', wants_academic)) if wanted]
        journal.decide(execution, 'plan_created', 'Research plan created.',
                       reason=f'Level {run.education_level.lower()}; materials: '
                              f'{", ".join(run.material_types) or "all"}; AI mode {run.llm_mode}.',
                       next_action='Start ' + ' and '.join(first or ['Document Analysis']) + '.')
    sequence += 1
    if _wants(run, MaterialType.WEB):
        journal.handoff(run, AGENT_BOSS, AGENT_WEB_RESEARCH, 'TASK: search web and university materials')
    if _wants(run, *ACADEMIC_MATERIAL_TYPES):
        journal.handoff(run, AGENT_BOSS, AGENT_ACADEMIC_RESEARCH, 'TASK: search academic materials')

    candidates = []
    _check(run, budget)
    _set_status(run, ResearchRunStatus.SEARCHING, 'Web Research')
    if _wants(run, MaterialType.WEB):
        try:
            sequence, web_candidates = web_research.run(run, sequence)
            candidates.extend(web_candidates)
            journal.handoff(run, AGENT_WEB_RESEARCH, AGENT_DOCUMENT_RETRIEVAL, f'{len(web_candidates)} web results',
                            count=len(web_candidates))
        except Exception as exc:
            logger.exception('Research run %s: Web Research crashed', run.pk)
            degraded = True
            issues.append(f'Web Research failed: {exc}')
            sequence += 1

    _check(run, budget)
    _set_status(run, ResearchRunStatus.SEARCHING, 'Academic Research')
    if _wants(run, *ACADEMIC_MATERIAL_TYPES):
        try:
            sequence, academic_candidates = academic_research.run(run, sequence)
            candidates.extend(academic_candidates)
            journal.handoff(run, AGENT_ACADEMIC_RESEARCH, AGENT_DOCUMENT_RETRIEVAL,
                            f'{len(academic_candidates)} academic results', count=len(academic_candidates))
        except Exception as exc:
            logger.exception('Research run %s: Academic Research crashed', run.pk)
            degraded = True
            issues.append(f'Academic Research failed: {exc}')
            sequence += 1

    _check(run, budget)
    _set_status(run, ResearchRunStatus.ANALYZING, 'Document Retrieval')
    try:
        sequence, retrieved_sources = document_retrieval.run(run, sequence, candidates, budget)
    except (BudgetExceeded, RunCancelled):
        raise
    except Exception as exc:
        logger.exception('Research run %s: Document Retrieval crashed', run.pk)
        degraded = True
        issues.append(f'Document Retrieval failed: {exc}')
        retrieved_sources = []
        sequence += 1

    _check(run, budget)
    _set_status(run, ResearchRunStatus.ANALYZING, 'Document Analysis')
    try:
        journal.handoff(run, AGENT_DOCUMENT_RETRIEVAL, AGENT_DOCUMENT_ANALYSIS,
                        f'{len(retrieved_sources)} documents', count=len(retrieved_sources))
        sequence, analyzed_sources = document_analysis.run(run, sequence, retrieved_sources, budget)
    except (BudgetExceeded, RunCancelled):
        raise
    except Exception as exc:
        logger.exception('Research run %s: Document Analysis crashed', run.pk)
        degraded = True
        issues.append(f'Document Analysis failed: {exc}')
        analyzed_sources = [s for s in retrieved_sources if not s.is_duplicate]
        sequence += 1

    _check(run, budget)
    accepted_sources = []
    if run.mode != RunMode.SEARCH:  # a plain materials search stops after Document Analysis
        _set_status(run, ResearchRunStatus.VALIDATING, 'Source Validator')
        try:
            journal.handoff(run, AGENT_DOCUMENT_ANALYSIS, AGENT_SOURCE_VALIDATOR,
                            f'{len(analyzed_sources)} documents to validate', count=len(analyzed_sources))
            sequence, accepted_sources = source_validator.run(run, sequence, analyzed_sources)
            accepted_sources = source_validator.with_provisional(run, accepted_sources, analyzed_sources)
        except Exception as exc:
            logger.exception('Research run %s: Source Validator crashed', run.pk)
            degraded = True
            issues.append(f'Source Validator failed: {exc}')
            accepted_sources = []
            sequence += 1

    lecture = None
    if run.generate_lecture or run.generate_assignment:
        journal.handoff(run, AGENT_SOURCE_VALIDATOR,
                        AGENT_LECTURE_BUILDER if run.generate_lecture else AGENT_ASSIGNMENT_GENERATOR,
                        f'{len(accepted_sources)} approved sources', count=len(accepted_sources))
    if run.generate_lecture:
        _check(run, budget)
        _set_status(run, ResearchRunStatus.BUILDING_LECTURE, 'Lecture Builder')
        try:
            sequence, lecture = lecture_builder.generate(run, sequence, accepted_sources)
        except Exception as exc:
            logger.exception('Research run %s: Lecture Builder crashed', run.pk)
            degraded = True
            issues.append(f'Lecture Builder failed: {exc}')
            lecture = None
            sequence += 1

        if lecture is not None and lecture.status == LectureStatus.INSUFFICIENT_SOURCES:
            issues.append('Lecture Builder: insufficient sources to build a sound lecture on this topic.')
        elif lecture is not None and accepted_sources:
            lecture_revision = 0
            while True:
                _check(run, budget)
                _set_status(run, ResearchRunStatus.REVIEWING_LECTURE, 'Final Reviewer (lecture)')
                journal.handoff(run, AGENT_LECTURE_BUILDER, AGENT_FINAL_REVIEWER, f'Lecture v{lecture.version}',
                                target='lecture', version=lecture.version)
                try:
                    sequence, lecture_result = final_reviewer.review_lecture(run, sequence, lecture, accepted_sources)
                except Exception as exc:
                    logger.exception('Research run %s: Final Reviewer (lecture) crashed', run.pk)
                    degraded = True
                    issues.append(f'Final Reviewer (lecture) failed: {exc}')
                    break
                if lecture_result.decision == 'approved':
                    if run.generate_assignment:
                        journal.handoff(run, AGENT_FINAL_REVIEWER, AGENT_ASSIGNMENT_GENERATOR,
                                        f'Lecture v{lecture.version} approved', target='lecture')
                    break
                journal.handoff(run, AGENT_FINAL_REVIEWER, AGENT_LECTURE_BUILDER, 'REVISION REQUIRED',
                                target='lecture', revision=True, issues=lecture_result.issues[:5])
                lecture_revision += 1
                run.lecture_revision_count = lecture_revision
                run.save(update_fields=['lecture_revision_count', 'updated_at'])
                if lecture_revision >= settings.RESEARCH_LAB_MAX_LECTURE_REVISIONS:
                    # The best draft is kept and labelled; hitting the review limit is not a failure.
                    lecture.status = LectureStatus.REVISION_LIMIT_REACHED
                    lecture.save(update_fields=['status'])
                    break
                _check(run, budget)
                _set_status(run, ResearchRunStatus.BUILDING_LECTURE, 'Lecture Builder (revision)')
                try:
                    sequence, lecture = lecture_builder.generate(
                        run, sequence, accepted_sources,
                        previous_draft={'title': lecture.title, 'learning_objectives': lecture.learning_objectives,
                                       'sections': lecture.content_json.get('sections', []),
                                       'summary': lecture.content_json.get('summary', '')},
                        feedback=lecture_result.issues,
                    )
                except Exception as exc:
                    logger.exception('Research run %s: Lecture Builder (revision) crashed', run.pk)
                    degraded = True
                    issues.append(f'Lecture Builder (revision) failed: {exc}')
                    break

    #: Only a usably-grounded lecture is handed to the Assignment Generator — never one flagged
    #: insufficient_sources, which carries little more than a "couldn't do it" note.
    lecture_for_assignment = lecture if lecture and lecture.status != LectureStatus.INSUFFICIENT_SOURCES else None

    if run.generate_assignment:
        _check(run, budget)
        _set_status(run, ResearchRunStatus.GENERATING, 'Assignment Generator')
        try:
            sequence, assignment = assignment_generator.generate(run, sequence, accepted_sources,
                                                                  lecture=lecture_for_assignment)
        except Exception as exc:
            logger.exception('Research run %s: Assignment Generator crashed', run.pk)
            degraded = True
            issues.append(f'Assignment Generator failed: {exc}')
            assignment = None
            sequence += 1

        if assignment is not None and accepted_sources:
            revision = 0
            while True:
                _check(run, budget)
                _set_status(run, ResearchRunStatus.REVIEWING, 'Final Reviewer')
                journal.handoff(run, AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER,
                                f'Assignment v{revision + 1}', target='assignment', version=revision + 1)
                try:
                    sequence, result = final_reviewer.review(run, sequence, assignment, accepted_sources)
                except Exception as exc:
                    logger.exception('Research run %s: Final Reviewer crashed', run.pk)
                    degraded = True
                    issues.append(f'Final Reviewer failed: {exc}')
                    break
                if result.decision == 'approved':
                    break
                journal.handoff(run, AGENT_FINAL_REVIEWER, AGENT_ASSIGNMENT_GENERATOR, 'REVISION REQUIRED',
                                target='assignment', revision=True, issues=result.issues[:5])
                revision += 1
                run.revision_count = revision
                run.save(update_fields=['revision_count', 'updated_at'])
                if revision >= settings.RESEARCH_LAB_MAX_REVISION_CYCLES:
                    assignment.review_status = ReviewStatus.REVISION_LIMIT_REACHED
                    assignment.save(update_fields=['review_status'])
                    break
                _check(run, budget)
                _set_status(run, ResearchRunStatus.GENERATING, 'Assignment Generator (revision)')
                try:
                    sequence, assignment = assignment_generator.generate(
                        run, sequence, accepted_sources,
                        previous_draft={'title': assignment.title, 'objectives': assignment.objectives,
                                       'instructions': assignment.instructions, 'questions': assignment.questions},
                        feedback=result.issues, lecture=lecture_for_assignment,
                    )
                except Exception as exc:
                    logger.exception('Research run %s: Assignment Generator (revision) crashed', run.pk)
                    degraded = True
                    issues.append(f'Assignment Generator (revision) failed: {exc}')
                    break

    if issues:
        run.error_message = '; '.join(issues)[:2000]
    return run, degraded, True


_END_AGENT_STATUS = {
    ResearchRunStatus.COMPLETED: 'completed', ResearchRunStatus.PARTIAL: 'completed',
    ResearchRunStatus.FAILED: 'failed', ResearchRunStatus.CANCELLED: 'cancelled',
}


def _announce_end(run: ResearchRun) -> None:
    """Final events: the Boss's own terminal status (it orchestrates until the very end), the run's
    status, and — for a cancelled/failed run — closing any agent step that was still showing as running."""
    if run.status in (ResearchRunStatus.CANCELLED, ResearchRunStatus.FAILED):
        for execution in run.agent_executions.filter(status='RUNNING'):
            events.emit(run, events.AGENT_FAILED, execution.agent,
                        info=(execution.metadata or {}).get('model_info'),
                        status='cancelled' if run.status == ResearchRunStatus.CANCELLED else 'failed',
                        summary=run.error_message[:200] or run.get_status_display())
    end_status = _END_AGENT_STATUS.get(run.status, 'completed')
    events.emit(run, events.AGENT_FAILED if end_status in ('failed', 'cancelled') else events.AGENT_COMPLETED,
                AGENT_BOSS, status=end_status,
                summary=f'Run {run.get_status_display().lower()}', info=events.model_info(run, AGENT_BOSS))
    events.emit(run, events.RUN_STATUS, AGENT_BOSS, status=run.status.lower(), run_status=run.status,
                summary=run.error_message[:300] or run.get_status_display())


def run_workflow(run_id: int) -> ResearchRun:
    try:
        run, degraded, ran = _execute(run_id)
        if not ran:
            return run  # already terminal (or a duplicate delivery) — leave it exactly as it is
        run.refresh_from_db(fields=['cancel_requested'])
        if run.cancel_requested:
            run.status = ResearchRunStatus.CANCELLED
        else:
            run.status = ResearchRunStatus.PARTIAL if degraded else ResearchRunStatus.COMPLETED
        run.current_step = ''
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'current_step', 'error_message', 'finished_at', 'updated_at'])
        _announce_end(run)
        return run
    except RunCancelled:
        ResearchRun.objects.filter(pk=run_id).update(
            status=ResearchRunStatus.CANCELLED, current_step='', finished_at=timezone.now())
        _announce_end(ResearchRun.objects.get(pk=run_id))
    except BudgetExceeded as exc:
        logger.info('Research run %s hit its budget: %s', run_id, exc)
        ResearchRun.objects.filter(pk=run_id).update(
            status=ResearchRunStatus.PARTIAL, error_message=str(exc)[:2000], current_step='',
            finished_at=timezone.now())
        _announce_end(ResearchRun.objects.get(pk=run_id))
    except Exception as exc:
        logger.exception('Research run %s failed', run_id)
        ResearchRun.objects.filter(pk=run_id).update(
            status=ResearchRunStatus.FAILED, error_message=f'{type(exc).__name__}: {exc}'[:2000],
            current_step='', finished_at=timezone.now())
        _announce_end(ResearchRun.objects.get(pk=run_id))
    return ResearchRun.objects.get(pk=run_id)
