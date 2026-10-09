from django.db.models import QuerySet

from accounts.permissions import is_admin
from research_lab.models import (AgentExecution, Assignment, GeneratedLecture, ResearchRun, ResearchSource,
                                 ToolExecution)


def runs_for_user(user) -> QuerySet[ResearchRun]:
    """Admins see every run; everyone else sees only their own — a teacher never sees a colleague's
    research run (spec section 20: "пользователь не должен видеть чужие ResearchRun")."""
    qs = ResearchRun.objects.select_related('user')
    return qs if is_admin(user) else qs.filter(user=user)


def sources_for_user(user) -> QuerySet[ResearchSource]:
    return ResearchSource.objects.select_related('run', 'document').filter(run__in=runs_for_user(user).values('pk'))


def agent_executions_for_user(user) -> QuerySet[AgentExecution]:
    return AgentExecution.objects.select_related('run', 'generation_run').filter(
        run__in=runs_for_user(user).values('pk'))


def tool_executions_for_user(user) -> QuerySet[ToolExecution]:
    return ToolExecution.objects.select_related('run').filter(run__in=runs_for_user(user).values('pk'))


def assignments_for_user(user) -> QuerySet[Assignment]:
    return Assignment.objects.select_related('run').filter(run__in=runs_for_user(user).values('pk'))


def lectures_for_user(user) -> QuerySet[GeneratedLecture]:
    return GeneratedLecture.objects.select_related('run').filter(run__in=runs_for_user(user).values('pk'))
