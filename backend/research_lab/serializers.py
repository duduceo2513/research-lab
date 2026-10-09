from django.conf import settings
from rest_framework import serializers

from core.admin_utils import truncated
from llm.models import LLMConfiguration
from research_lab.models import (AgentExecution, Assignment, EducationLevel, GeneratedLecture, LLMMode,
                                 MaterialType, ModuleSettings, ResearchRun, ResearchSource, RunMode,
                                 SourceProvider, ToolExecution)
from research_lab.services.module_settings import provider_statuses


class ResearchRunSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ResearchRun
        fields = ['id', 'user', 'user_email', 'mode', 'selected_providers', 'topic', 'description',
                  'education_level', 'language', 'material_types', 'publication_year_from', 'publication_year_to', 'open_access_only',
                  'generate_assignment', 'assignment_type', 'difficulty',
                  'generate_lecture', 'lecture_target_duration_minutes', 'lecture_detail_level',
                  'lecture_include_examples', 'lecture_include_summary', 'lecture_revision_count',
                  'llm_mode', 'agent_model_overrides', 'status', 'current_step', 'error_message',
                  'cancel_requested', 'revision_count', 'is_active', 'started_at', 'finished_at',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'status', 'current_step', 'error_message', 'cancel_requested',
                           'revision_count', 'lecture_revision_count', 'started_at', 'finished_at',
                           'created_at', 'updated_at']
        extra_kwargs = {'llm_mode': {'default': lambda: ModuleSettings.load().default_llm_mode}}

    def validate_material_types(self, value):
        valid = set(MaterialType.values)
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f'Must be a list of: {", ".join(sorted(valid))}.')
        return value

    def validate_selected_providers(self, value):
        valid = set(SourceProvider.values)
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f'Must be a list of: {", ".join(sorted(valid))}.')
        return value

    def validate_agent_model_overrides(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Must be an object mapping agent name -> LLMConfiguration id.')
        ids = [v for v in value.values() if v is not None]
        if ids and not LLMConfiguration.objects.filter(pk__in=ids).count() == len(set(ids)):
            raise serializers.ValidationError('One or more referenced LLM configurations do not exist.')
        return value

    def validate(self, attrs):
        if attrs.get('mode') == RunMode.SEARCH and not ModuleSettings.load().materials_search_enabled:
            raise serializers.ValidationError(
                {'mode': 'Materials search is switched off in Settings → Research Lab.'})
        if attrs.get('mode') == RunMode.SEARCH:
            # A materials search only finds, downloads and extracts: nothing is validated or written.
            attrs['generate_assignment'] = False
            attrs['generate_lecture'] = False
        year_from = attrs.get('publication_year_from')
        year_to = attrs.get('publication_year_to')
        if year_from and year_to and year_from > year_to:
            raise serializers.ValidationError({'publication_year_to': 'Must be on/after publication_year_from.'})
        if attrs.get('llm_mode') == LLMMode.CUSTOM and not attrs.get('agent_model_overrides'):
            raise serializers.ValidationError(
                {'agent_model_overrides': 'Required when llm_mode is CUSTOM.'})
        return attrs

    def create(self, validated_data):
        return ResearchRun.objects.create(user=self.context['request'].user, **validated_data)


class ResearchRunListSerializer(ResearchRunSerializer):
    class Meta(ResearchRunSerializer.Meta):
        fields = ['id', 'mode', 'topic', 'education_level', 'status', 'current_step', 'generate_assignment',
                  'generate_lecture', 'is_active', 'created_at', 'finished_at']
        read_only_fields = fields


class ResearchSourceSerializer(serializers.ModelSerializer):
    text_preview = serializers.SerializerMethodField()
    # What happened to the document behind this result (download / extraction), for the materials list.
    document_status = serializers.SerializerMethodField()
    document_format = serializers.SerializerMethodField()
    has_file = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    text_length = serializers.SerializerMethodField()
    document_error = serializers.SerializerMethodField()

    class Meta:
        model = ResearchSource
        fields = ['id', 'run', 'provider', 'source_type', 'title', 'url', 'authors', 'publisher',
                  'published_at', 'doi', 'isbn', 'abstract', 'citation_count', 'open_access', 'pdf_url',
                  'is_duplicate', 'duplicate_of', 'relevance_score', 'authority_score',
                  'educational_value_score', 'academic_credibility_score', 'level_match_score',
                  'recency_score', 'completeness_score', 'overall_score', 'decision', 'decision_reasons',
                  'validated_at', 'text_preview', 'created_at', 'document_status', 'document_format',
                  'has_file', 'file_name', 'file_size', 'text_length', 'document_error']
        read_only_fields = fields

    def _document(self, obj):
        return getattr(obj, 'document', None)

    def get_text_preview(self, obj) -> str:
        document = self._document(obj)
        return truncated(document.text if document and document.text else obj.abstract, 300)

    def get_document_status(self, obj) -> str:
        document = self._document(obj)
        return document.status if document else 'PENDING'

    def get_document_format(self, obj) -> str:
        document = self._document(obj)
        return document.content_type if document else ''

    def get_has_file(self, obj) -> bool:
        document = self._document(obj)
        return bool(document and document.file)

    def get_file_name(self, obj) -> str:
        document = self._document(obj)
        return document.file_name if document else ''

    def get_file_size(self, obj) -> int:
        document = self._document(obj)
        return document.file_size if document else 0

    def get_text_length(self, obj) -> int:
        document = self._document(obj)
        return document.text_length if document else len(obj.abstract)

    def get_document_error(self, obj) -> str:
        document = self._document(obj)
        return document.error_message if document else ''


class ResearchSourceDetailSerializer(ResearchSourceSerializer):
    """The full card: everything above plus the complete text (API full text, or extracted from the
    downloaded document, or — failing both — the description) and the provider's raw metadata."""

    text = serializers.SerializerMethodField()
    text_origin = serializers.SerializerMethodField()
    metadata = serializers.JSONField(read_only=True)
    fetch_method = serializers.SerializerMethodField()

    class Meta(ResearchSourceSerializer.Meta):
        fields = [*ResearchSourceSerializer.Meta.fields, 'text', 'text_origin', 'metadata', 'fetch_method']
        read_only_fields = fields

    def get_text(self, obj) -> str:
        document = self._document(obj)
        return (document.text if document and document.text else obj.abstract) or ''

    def get_text_origin(self, obj) -> str:
        """``document`` (extracted from a file/page), ``description`` (only what the API returned) or ``none``."""
        document = self._document(obj)
        if document and document.text and document.status in ('EXTRACTED', 'FETCHED'):
            return 'document'
        if document and document.text or obj.abstract:
            return 'description'
        return 'none'

    def get_fetch_method(self, obj) -> str:
        document = self._document(obj)
        return document.fetch_method if document else ''


class AgentExecutionSerializer(serializers.ModelSerializer):
    generation_run_tokens = serializers.IntegerField(source='generation_run.total_tokens', read_only=True,
                                                      default=None)
    generation_run_cost = serializers.CharField(source='generation_run.estimated_cost', read_only=True,
                                                default=None)

    class Meta:
        model = AgentExecution
        fields = ['id', 'run', 'agent', 'sequence', 'status', 'generation_run', 'generation_run_tokens',
                  'generation_run_cost', 'input_summary', 'output_summary', 'activity', 'error_message', 'started_at',
                  'finished_at', 'latency_ms']
        read_only_fields = fields


class ToolExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolExecution
        fields = ['id', 'run', 'agent_execution', 'tool', 'status', 'request_summary', 'response_summary',
                  'error_message', 'latency_ms', 'created_at']
        read_only_fields = fields


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ['id', 'run', 'title', 'objectives', 'instructions', 'questions', 'grading_criteria',
                  'references', 'answer_key', 'assignment_type', 'difficulty', 'review_status',
                  'review_score', 'review_issues', 'generation_run', 'reviewer_generation_run',
                  'created_at', 'updated_at']
        read_only_fields = fields


class GeneratedLectureSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneratedLecture
        fields = ['id', 'run', 'version', 'title', 'learning_objectives', 'content_json', 'plain_text',
                  'status', 'review_score', 'review_result', 'generation_run', 'reviewer_generation_run',
                  'created_at']
        read_only_fields = fields


class ProviderStatusSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    configured = serializers.BooleanField()
    enabled = serializers.BooleanField()
    #: active | disabled | missing_key | error
    state = serializers.CharField()
    missing_settings = serializers.ListField(child=serializers.CharField())
    last_error = serializers.CharField(allow_blank=True)
    last_checked = serializers.CharField(allow_null=True)
    metadata_only = serializers.BooleanField()


class ConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    education_levels = serializers.ListField(child=serializers.CharField())
    material_types = serializers.ListField(child=serializers.CharField())
    max_search_queries = serializers.IntegerField()
    max_results_per_query = serializers.IntegerField()
    max_documents = serializers.IntegerField()
    max_revision_cycles = serializers.IntegerField()
    default_llm_mode = serializers.CharField()
    materials_search_enabled = serializers.BooleanField()
    providers = ProviderStatusSerializer(many=True)


def build_config() -> dict:
    return {
        'enabled': settings.RESEARCH_LAB_ENABLED,
        'education_levels': EducationLevel.values,
        'material_types': MaterialType.values,
        'max_search_queries': settings.RESEARCH_LAB_MAX_SEARCH_QUERIES,
        'max_results_per_query': settings.RESEARCH_LAB_MAX_RESULTS_PER_QUERY,
        'max_documents': settings.RESEARCH_LAB_MAX_DOCUMENTS,
        'max_revision_cycles': settings.RESEARCH_LAB_MAX_REVISION_CYCLES,
        'default_llm_mode': ModuleSettings.load().default_llm_mode,
        'materials_search_enabled': ModuleSettings.load().materials_search_enabled,
        'providers': provider_statuses(),
    }


class ModuleSettingsSerializer(serializers.ModelSerializer):
    providers = serializers.SerializerMethodField()

    class Meta:
        model = ModuleSettings
        fields = ['default_llm_mode', 'materials_search_enabled', 'disabled_providers', 'providers', 'updated_at']
        read_only_fields = ['providers', 'updated_at']

    def get_providers(self, obj) -> list[dict]:
        return provider_statuses()

    def validate_disabled_providers(self, value):
        valid = set(SourceProvider.values)
        if not isinstance(value, list) or not set(value) <= valid:
            raise serializers.ValidationError(f'Must be a list of: {", ".join(sorted(valid))}.')
        return value
