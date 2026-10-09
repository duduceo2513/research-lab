from django.contrib import admin, messages

from core.admin_utils import TimestampedAdminMixin, admin_link, preview_block
from research_lab.models import (ACTIVE_RUN_STATUSES, AgentExecution, Assignment, GeneratedLecture,
                                 ModuleSettings, ResearchDocument, ResearchRun, ResearchSource, ToolExecution)


@admin.register(ModuleSettings)
class ModuleSettingsAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ('default_llm_mode', 'disabled_providers', 'updated_at')

    def has_add_permission(self, request):
        return not ModuleSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class ResearchSourceInline(admin.TabularInline):
    model = ResearchSource
    extra = 0
    max_num = 0
    can_delete = False
    fields = ('title', 'provider', 'decision', 'overall_score', 'is_duplicate')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class AgentExecutionInline(admin.TabularInline):
    model = AgentExecution
    extra = 0
    max_num = 0
    can_delete = False
    fields = ('sequence', 'agent', 'status', 'latency_ms', 'started_at')
    readonly_fields = fields
    ordering = ('sequence',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ResearchRun)
class ResearchRunAdmin(TimestampedAdminMixin, admin.ModelAdmin):
    list_display = ('topic', 'user', 'education_level', 'status', 'llm_mode', 'generate_assignment',
                    'generate_lecture', 'created_at')
    list_filter = ('status', 'education_level', 'llm_mode', 'generate_assignment', 'generate_lecture')
    search_fields = ('topic', 'description', 'user__email')
    autocomplete_fields = ('user',)
    list_select_related = ('user',)
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = ['cancel_selected']
    readonly_fields = ('status', 'current_step', 'error_message', 'started_at',
                       'finished_at', 'revision_count', 'lecture_revision_count', 'created_at', 'updated_at')
    inlines = [AgentExecutionInline, ResearchSourceInline]
    fieldsets = (
        (None, {'fields': ('user', 'topic', 'description', 'education_level', 'language')}),
        ('Scope', {'fields': ('material_types', 'publication_year_from', 'publication_year_to',
                              'open_access_only')}),
        ('Assignment', {'fields': ('generate_assignment', 'assignment_type', 'difficulty')}),
        ('Lecture', {'fields': ('generate_lecture', 'lecture_target_duration_minutes', 'lecture_detail_level',
                                'lecture_include_examples', 'lecture_include_summary', 'lecture_revision_count')}),
        ('LLM', {'fields': ('llm_mode', 'agent_model_overrides')}),
        ('Execution', {'fields': ('status', 'current_step', 'error_message', 'cancel_requested',
                                  'revision_count', 'started_at', 'finished_at')}),
        ('Extra', {'fields': ('metadata', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.action(description='Request cancellation of selected (active) runs')
    def cancel_selected(self, request, queryset):
        updated = queryset.filter(status__in=ACTIVE_RUN_STATUSES).update(cancel_requested=True)
        self.message_user(request, f'{updated} run(s) will stop at their next checkpoint.', messages.SUCCESS)


class ResearchDocumentInline(admin.StackedInline):
    model = ResearchDocument
    extra = 0
    max_num = 1
    can_delete = False
    readonly_fields = ('status', 'fetch_method', 'content_type', 'text_full_preview', 'text_length',
                       'fetch_latency_ms', 'extract_latency_ms', 'error_message')
    fields = readonly_fields

    @admin.display(description='Text')
    def text_full_preview(self, obj):
        return preview_block(obj.text) if obj.pk else '-'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ResearchSource)
class ResearchSourceAdmin(admin.ModelAdmin):
    list_display = ('title', 'run_link', 'provider', 'source_type', 'decision', 'overall_score',
                    'is_duplicate', 'created_at')
    list_filter = ('provider', 'source_type', 'decision', 'is_duplicate', 'open_access')
    search_fields = ('title', 'doi', 'isbn', 'url')
    autocomplete_fields = ('run', 'duplicate_of')
    list_select_related = ('run',)
    list_per_page = 50
    readonly_fields = ('relevance_score', 'authority_score', 'educational_value_score',
                       'academic_credibility_score', 'level_match_score', 'recency_score',
                       'completeness_score', 'overall_score', 'decision', 'decision_reasons',
                       'validated_at', 'content_hash', 'created_at')
    inlines = [ResearchDocumentInline]

    @admin.display(description='Run', ordering='run__topic')
    def run_link(self, obj):
        return admin_link(obj.run, obj.run.topic)


@admin.register(AgentExecution)
class AgentExecutionAdmin(admin.ModelAdmin):
    list_display = ('run_link', 'sequence', 'agent', 'status', 'latency_ms', 'started_at')
    list_filter = ('agent', 'status')
    search_fields = ('run__topic',)
    autocomplete_fields = ('run', 'generation_run')
    list_select_related = ('run',)
    list_per_page = 50
    readonly_fields = ('run', 'agent', 'sequence', 'status', 'generation_run', 'input_summary',
                       'output_summary', 'error_message', 'started_at', 'finished_at', 'latency_ms')

    def has_add_permission(self, request):
        return False

    @admin.display(description='Run', ordering='run__topic')
    def run_link(self, obj):
        return admin_link(obj.run, obj.run.topic)


@admin.register(ToolExecution)
class ToolExecutionAdmin(admin.ModelAdmin):
    list_display = ('run_link', 'tool', 'status', 'latency_ms', 'created_at')
    list_filter = ('tool', 'status')
    search_fields = ('run__topic',)
    autocomplete_fields = ('run', 'agent_execution')
    list_select_related = ('run',)
    list_per_page = 50
    readonly_fields = ('run', 'agent_execution', 'tool', 'status', 'request_summary', 'response_summary',
                       'error_message', 'latency_ms', 'created_at')

    def has_add_permission(self, request):
        return False

    @admin.display(description='Run', ordering='run__topic')
    def run_link(self, obj):
        return admin_link(obj.run, obj.run.topic)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'run_link', 'review_status', 'review_score', 'created_at')
    list_filter = ('review_status', 'assignment_type', 'difficulty')
    search_fields = ('title', 'run__topic')
    autocomplete_fields = ('run',)
    list_select_related = ('run',)
    list_per_page = 50
    readonly_fields = ('review_status', 'review_score', 'review_issues', 'generation_run',
                       'reviewer_generation_run', 'instructions_preview', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('run', 'title', 'assignment_type', 'difficulty')}),
        ('Content', {'fields': ('objectives', 'instructions_preview', 'questions', 'grading_criteria',
                                'references', 'answer_key')}),
        ('Review', {'fields': ('review_status', 'review_score', 'review_issues', 'generation_run',
                               'reviewer_generation_run')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    @admin.display(description='Run', ordering='run__topic')
    def run_link(self, obj):
        return admin_link(obj.run, obj.run.topic)

    @admin.display(description='Instructions')
    def instructions_preview(self, obj):
        return preview_block(obj.instructions)


@admin.register(GeneratedLecture)
class GeneratedLectureAdmin(admin.ModelAdmin):
    list_display = ('title', 'run_link', 'version', 'status', 'review_score', 'created_at')
    list_filter = ('status',)
    search_fields = ('title', 'run__topic')
    autocomplete_fields = ('run',)
    list_select_related = ('run',)
    list_per_page = 50
    readonly_fields = ('version', 'status', 'review_score', 'review_result', 'generation_run',
                       'reviewer_generation_run', 'plain_text_preview', 'created_at')
    fieldsets = (
        (None, {'fields': ('run', 'version', 'title', 'learning_objectives')}),
        ('Content', {'fields': ('content_json', 'plain_text_preview')}),
        ('Review', {'fields': ('status', 'review_score', 'review_result', 'generation_run',
                               'reviewer_generation_run')}),
        ('Timestamps', {'fields': ('created_at',)}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description='Run', ordering='run__topic')
    def run_link(self, obj):
        return admin_link(obj.run, obj.run.topic)

    @admin.display(description='Plain text')
    def plain_text_preview(self, obj):
        return preview_block(obj.plain_text)
