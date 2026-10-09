from rest_framework import serializers

from llm.models import GenerationRun, LLMConfiguration, LLMProvider, PromptTemplate


class LLMProviderSerializer(serializers.ModelSerializer):
    """``secret_env_name`` is only the *name* of an environment variable; keys are never stored or returned."""

    class Meta:
        model = LLMProvider
        fields = ['id', 'code', 'display_name', 'base_url', 'secret_env_name', 'is_active', 'metadata']
        read_only_fields = ['id']

    def validate_secret_env_name(self, value):
        if value and (value.startswith(('sk-', 'xi-')) or not value.replace('_', '').isalnum()):
            raise serializers.ValidationError('Provide an environment variable NAME, never the key itself.')
        return value


class LLMConfigurationSerializer(serializers.ModelSerializer):
    provider_code = serializers.CharField(source='provider.code', read_only=True)

    class Meta:
        model = LLMConfiguration
        fields = ['id', 'provider', 'provider_code', 'name', 'model_name', 'temperature', 'max_tokens',
                  'context_window', 'supports_streaming', 'supports_tools', 'supports_vision',
                  'is_default', 'is_active', 'metadata', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {'is_default': {'validators': []}}

    def _demote(self, exclude_pk=None):
        qs = LLMConfiguration.objects.filter(is_default=True)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        qs.update(is_default=False)

    def create(self, validated_data):
        from django.db import transaction

        with transaction.atomic():
            if validated_data.get('is_default'):
                self._demote()
            return super().create(validated_data)

    def update(self, instance, validated_data):
        from django.db import transaction

        with transaction.atomic():
            if validated_data.get('is_default'):
                self._demote(instance.pk)
            return super().update(instance, validated_data)


class PromptTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptTemplate
        fields = ['id', 'name', 'code', 'system_prompt', 'user_template', 'version', 'is_active',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GenerationRunSerializer(serializers.ModelSerializer):
    configuration_name = serializers.CharField(source='configuration.name', read_only=True)
    provider_code = serializers.CharField(source='configuration.provider.code', read_only=True)

    class Meta:
        model = GenerationRun
        fields = ['id', 'user', 'configuration', 'configuration_name', 'provider_code', 'prompt_template',
                  'question_text', 'system_prompt', 'user_prompt', 'response_text', 'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
                  'first_token_latency_ms', 'tokens_per_second', 'estimated_cost', 'status',
                  'error_message', 'metadata', 'created_at']
        read_only_fields = fields


class LocalModelsSerializer(serializers.Serializer):
    models = serializers.ListField(child=serializers.CharField())
    detail = serializers.CharField(required=False)
