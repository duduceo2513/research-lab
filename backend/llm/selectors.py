from django.db.models import QuerySet

from accounts.permissions import is_admin
from llm.models import GenerationRun


def generation_runs_for_user(user) -> QuerySet[GenerationRun]:
    """Admins see all LLM calls; everyone else the calls made by their own research runs (Research Lab
    tags every call with ``metadata.run_id``)."""
    qs = GenerationRun.objects.select_related('configuration', 'configuration__provider', 'prompt_template')
    if is_admin(user):
        return qs
    from research_lab.models import ResearchRun

    run_ids = list(ResearchRun.objects.filter(user=user).values_list('pk', flat=True))
    return qs.filter(metadata__run_id__in=run_ids)
