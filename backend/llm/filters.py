import django_filters

from llm.models import GenerationRun, LLMConfiguration, LLMProvider, PromptTemplate


class LLMProviderFilter(django_filters.FilterSet):
    class Meta:
        model = LLMProvider
        fields = ['code', 'is_active']


class LLMConfigurationFilter(django_filters.FilterSet):
    class Meta:
        model = LLMConfiguration
        fields = ['provider', 'is_default', 'is_active']


class PromptTemplateFilter(django_filters.FilterSet):
    class Meta:
        model = PromptTemplate
        fields = ['code', 'is_active', 'version']


class GenerationRunFilter(django_filters.FilterSet):
    provider = django_filters.CharFilter(field_name='configuration__provider__code')

    class Meta:
        model = GenerationRun
        fields = ['configuration', 'status', 'user', 'provider']
