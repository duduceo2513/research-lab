from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import MetadataMixin, TimestampedModel


class ProviderCode(models.TextChoices):
    OPENAI = 'OPENAI', 'OpenAI'
    ANTHROPIC = 'ANTHROPIC', 'Anthropic (Claude)'
    LOCAL = 'LOCAL', 'Local (OpenAI-compatible)'


class LLMProvider(MetadataMixin):
    """A backend that serves models. API keys are NEVER stored: ``secret_env_name`` only names the
    environment variable that holds the key (e.g. OPENAI_API_KEY)."""

    code = models.CharField('code', max_length=16, choices=ProviderCode.choices)
    display_name = models.CharField('display name', max_length=128, unique=True)
    base_url = models.URLField('base URL', blank=True, null=True,
                               help_text='Override the API endpoint (required for LOCAL).')
    secret_env_name = models.CharField('secret env variable', max_length=64, blank=True, null=True,
                                       help_text='Name of the environment variable holding the API key.')
    is_active = models.BooleanField('active', default=True)

    class Meta:
        verbose_name = 'LLM provider'
        verbose_name_plural = 'LLM providers'
        ordering = ['display_name']

    def __str__(self) -> str:
        return self.display_name

    def clean(self):
        super().clean()
        if self.secret_env_name and not self.secret_env_name.replace('_', '').isalnum():
            raise ValidationError({'secret_env_name': 'Must be an environment variable NAME, not a key.'})
        if self.secret_env_name and self.secret_env_name.startswith(('sk-', 'xi-')):
            raise ValidationError({'secret_env_name': 'This looks like an API key. Store keys in the environment.'})


class LLMConfiguration(TimestampedModel, MetadataMixin):
    """A concrete model + generation parameters.

    ``metadata`` keys understood by the platform:
      * ``pricing``: ``{"input_per_1m": 5.0, "output_per_1m": 25.0}`` (USD) → GenerationRun.estimated_cost
      * ``reasoning_effort`` / ``effort``: provider-specific effort control
    """

    provider = models.ForeignKey(LLMProvider, on_delete=models.PROTECT, related_name='configurations',
                                 verbose_name='provider')
    name = models.CharField('name', max_length=128, unique=True)
    model_name = models.CharField('model name', max_length=128)

    temperature = models.FloatField('temperature', default=0.2,
                                    validators=[MinValueValidator(0.0), MaxValueValidator(2.0)])
    max_tokens = models.PositiveIntegerField('max output tokens', default=1024,
                                             validators=[MinValueValidator(1)])
    context_window = models.PositiveIntegerField('context window', default=8192,
                                                 validators=[MinValueValidator(1)])

    supports_streaming = models.BooleanField('supports streaming', default=True)
    supports_tools = models.BooleanField('supports tools', default=False)
    supports_vision = models.BooleanField('supports vision', default=False)

    is_default = models.BooleanField('default', default=False)
    is_active = models.BooleanField('active', default=True)

    class Meta:
        verbose_name = 'LLM configuration'
        verbose_name_plural = 'LLM configurations'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['is_default'], condition=Q(is_default=True),
                                    name='uniq_default_llm_configuration'),
            models.CheckConstraint(condition=Q(temperature__gte=0, temperature__lte=2),
                                   name='llmconfig_temperature_0_2'),
            models.CheckConstraint(condition=Q(max_tokens__gte=1), name='llmconfig_max_tokens_positive'),
            models.CheckConstraint(condition=Q(context_window__gte=1), name='llmconfig_context_positive'),
        ]

    def __str__(self) -> str:
        return f'{self.name} ({self.model_name})'


class PromptCode(models.TextChoices):
    RESEARCH_SOURCE_VALIDATION = 'RESEARCH_SOURCE_VALIDATION', 'Research Lab: source validation'
    RESEARCH_SOURCE_VALIDATION_BATCH = 'RESEARCH_SOURCE_VALIDATION_BATCH', 'Research Lab: source validation (batch)'
    RESEARCH_ASSIGNMENT_GENERATION = 'RESEARCH_ASSIGNMENT_GENERATION', 'Research Lab: assignment generation'
    RESEARCH_ASSIGNMENT_REVISION = 'RESEARCH_ASSIGNMENT_REVISION', 'Research Lab: assignment revision'
    RESEARCH_ASSIGNMENT_REVIEW = 'RESEARCH_ASSIGNMENT_REVIEW', 'Research Lab: assignment review'
    RESEARCH_LECTURE_GENERATION = 'RESEARCH_LECTURE_GENERATION', 'Research Lab: lecture generation'
    RESEARCH_LECTURE_REVISION = 'RESEARCH_LECTURE_REVISION', 'Research Lab: lecture revision'
    RESEARCH_LECTURE_REVIEW = 'RESEARCH_LECTURE_REVIEW', 'Research Lab: lecture review'


class PromptTemplate(TimestampedModel):
    """Versioned prompt. Editing a prompt means adding a new version, so old runs stay reproducible.

    ``user_template`` placeholders are filled from the variables each agent passes (``{question}`` always).
    """

    name = models.CharField('name', max_length=128)
    code = models.CharField('code', max_length=32, choices=PromptCode.choices)
    system_prompt = models.TextField('system prompt')
    user_template = models.TextField('user template', blank=True)
    version = models.PositiveIntegerField('version', default=1, validators=[MinValueValidator(1)])
    is_active = models.BooleanField('active', default=True)

    class Meta:
        verbose_name = 'prompt template'
        verbose_name_plural = 'prompt templates'
        ordering = ['code', '-version']
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='uniq_prompt_code_version'),
            models.UniqueConstraint(fields=['code'], condition=Q(is_active=True),
                                    name='uniq_active_prompt_per_code'),
        ]

    def __str__(self) -> str:
        return f'{self.code} v{self.version}'


class GenerationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    RUNNING = 'RUNNING', 'Running'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'


class GenerationRun(MetadataMixin):
    """One LLM call with everything needed to reproduce and compare it.

    ``metadata`` records the effective sampling parameters (``params``), the provider code and, for
    Research Lab calls, the ``run_id`` and ``agent`` that made the call.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='generation_runs', verbose_name='user')
    configuration = models.ForeignKey(LLMConfiguration, on_delete=models.PROTECT,
                                      related_name='generation_runs', verbose_name='configuration')
    prompt_template = models.ForeignKey(PromptTemplate, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='generation_runs', verbose_name='prompt template')

    question_text = models.TextField('question')
    system_prompt = models.TextField('system prompt', blank=True)
    user_prompt = models.TextField('user prompt', blank=True)
    response_text = models.TextField('response', blank=True)

    input_tokens = models.PositiveIntegerField('input tokens', null=True, blank=True)
    output_tokens = models.PositiveIntegerField('output tokens', null=True, blank=True)
    total_tokens = models.PositiveIntegerField('total tokens', null=True, blank=True)

    latency_ms = models.PositiveIntegerField('latency (ms)', default=0)
    first_token_latency_ms = models.PositiveIntegerField('first token latency (ms)', null=True, blank=True)
    tokens_per_second = models.FloatField('tokens per second', null=True, blank=True)

    estimated_cost = models.DecimalField('estimated cost (USD)', max_digits=12, decimal_places=6,
                                         null=True, blank=True)

    status = models.CharField('status', max_length=16, choices=GenerationStatus.choices,
                              default=GenerationStatus.PENDING)
    error_message = models.TextField('error message', blank=True)
    created_at = models.DateTimeField('created at', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'generation run'
        verbose_name_plural = 'generation runs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['configuration', 'status'], name='genrun_cfg_status_idx'),
            models.Index(fields=['status', 'created_at'], name='genrun_status_created_idx'),
        ]

    def __str__(self) -> str:
        return f'Generation #{self.pk} [{self.status}]'
