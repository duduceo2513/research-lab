from django.contrib import admin

from core.admin_utils import TimestampedAdminMixin, preview_block
from llm.models import GenerationRun, LLMConfiguration, LLMProvider, PromptTemplate


@admin.register(LLMProvider)
class LLMProviderAdmin(admin.ModelAdmin):
    list_display = ('code', 'display_name', 'base_url', 'secret_env_name', 'is_active')
    list_filter = ('code', 'is_active')
    search_fields = ('display_name', 'base_url')
    list_per_page = 50
    fieldsets = (
        (None, {'fields': ('code', 'display_name', 'is_active')}),
        ('Connection', {
            'fields': ('base_url', 'secret_env_name'),
            'description': 'API keys are never stored here: enter only the NAME of the environment '
                           'variable (e.g. OPENAI_API_KEY) that holds the key on the server.',
        }),
        ('Extra', {'fields': ('metadata',), 'classes': ('collapse',)}),
    )


@admin.register(LLMConfiguration)
class LLMConfigurationAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'provider', 'model_name', 'temperature', 'max_tokens', 'context_window',
                    'is_default', 'is_active')
    list_filter = ('provider', 'is_default', 'is_active', 'supports_streaming')
    search_fields = ('name', 'model_name')
    list_select_related = ('provider',)
    list_per_page = 50
    fieldsets = (
        (None, {'fields': ('name', 'provider', 'model_name', 'is_default', 'is_active')}),
        ('Generation parameters', {'fields': ('temperature', 'max_tokens', 'context_window')}),
        ('Capabilities', {'fields': ('supports_streaming', 'supports_tools', 'supports_vision')}),
        ('Extra (pricing, effort…)', {'fields': ('metadata',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(PromptTemplate)
class PromptTemplateAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'code', 'version', 'is_active', 'updated_at')
    list_filter = ('code', 'is_active')
    search_fields = ('name', 'system_prompt', 'user_template')
    list_per_page = 50
    fieldsets = (
        (None, {'fields': ('name', 'code', 'version', 'is_active')}),
        ('Prompts', {'fields': ('system_prompt', 'user_template'),
                     'description': 'Do not edit a used version: add a new one so old runs stay reproducible.'}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(GenerationRun)
class GenerationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'configuration', 'status', 'latency_ms', 'input_tokens',
                    'output_tokens', 'estimated_cost', 'created_at')
    list_filter = ('status', 'configuration', 'configuration__provider')
    search_fields = ('question_text', 'response_text')
    list_select_related = ('configuration',)
    list_per_page = 50
    date_hierarchy = 'created_at'
    exclude = ('system_prompt', 'user_prompt', 'response_text', 'question_text')
    readonly_fields = ('user', 'configuration', 'prompt_template', 'status',
                       'error_message', 'question_view', 'system_prompt_view', 'user_prompt_view',
                       'response_view', 'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
                       'first_token_latency_ms', 'tokens_per_second', 'estimated_cost', 'metadata',
                       'created_at')
    fieldsets = (
        (None, {'fields': ('configuration', 'prompt_template', 'user', 'status', 'error_message')}),
        ('Prompt & response', {'fields': ('question_view', 'system_prompt_view', 'user_prompt_view',
                                          'response_view')}),
        ('Metrics', {'fields': ('input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
                                'first_token_latency_ms', 'tokens_per_second', 'estimated_cost')}),
        ('Extra', {'fields': ('metadata', 'created_at'), 'classes': ('collapse',)}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description='Question')
    def question_view(self, obj):
        return preview_block(obj.question_text, 2000)

    @admin.display(description='System prompt')
    def system_prompt_view(self, obj):
        return preview_block(obj.system_prompt)

    @admin.display(description='User prompt')
    def user_prompt_view(self, obj):
        return preview_block(obj.user_prompt, 8000)

    @admin.display(description='Response')
    def response_view(self, obj):
        return preview_block(obj.response_text, 8000)
