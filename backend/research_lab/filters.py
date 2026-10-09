import django_filters

from research_lab.models import AgentExecution, ResearchRun, ResearchSource, ToolExecution


class ResearchRunFilter(django_filters.FilterSet):
    class Meta:
        model = ResearchRun
        fields = ['status', 'education_level', 'generate_assignment', 'generate_lecture']


class ResearchSourceFilter(django_filters.FilterSet):
    class Meta:
        model = ResearchSource
        fields = ['run', 'provider', 'source_type', 'decision', 'is_duplicate']


class AgentExecutionFilter(django_filters.FilterSet):
    class Meta:
        model = AgentExecution
        fields = ['run', 'agent', 'status']


class ToolExecutionFilter(django_filters.FilterSet):
    class Meta:
        model = ToolExecution
        fields = ['run', 'tool', 'status']
