from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import SchemaSafeQuerysetMixin
from core.exceptions import ExternalServiceError
from accounts.permissions import IsAdminRole, IsAdminWriteStaffRead, IsTeacherOrAdmin
from llm import selectors
from llm.filters import (GenerationRunFilter, LLMConfigurationFilter, LLMProviderFilter,
                         PromptTemplateFilter)
from llm.models import LLMConfiguration, LLMProvider, ProviderCode, PromptTemplate
from llm.providers.factory import get_provider
from llm.providers.local_provider import list_local_models
from llm.serializers import (GenerationRunSerializer, LLMConfigurationSerializer, LLMProviderSerializer,
                             LocalModelsSerializer, PromptTemplateSerializer)


class LLMProviderViewSet(viewsets.ModelViewSet):
    queryset = LLMProvider.objects.all()
    serializer_class = LLMProviderSerializer
    permission_classes = [IsAdminWriteStaffRead]
    filterset_class = LLMProviderFilter
    search_fields = ['display_name']


class LLMConfigurationViewSet(viewsets.ModelViewSet):
    queryset = LLMConfiguration.objects.select_related('provider')
    serializer_class = LLMConfigurationSerializer
    permission_classes = [IsAdminWriteStaffRead]
    filterset_class = LLMConfigurationFilter
    search_fields = ['name', 'model_name']

    @action(detail=True, methods=['get'], permission_classes=[IsAdminRole])
    def health(self, request, pk=None):
        """Ping the provider (admin only; performs an outbound request)."""
        status_ = get_provider(self.get_object()).health_check()
        return Response({'ok': status_.ok, 'detail': status_.detail, 'latency_ms': status_.latency_ms})


class LocalModelsView(APIView):
    """Admin-only: the live list of models pulled on the local OpenAI-compatible server (Ollama,
    vLLM, ...), so the settings page never has to hardcode what's available on a given machine."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses=LocalModelsSerializer)
    def get(self, request):
        provider = LLMProvider.objects.filter(code=ProviderCode.LOCAL).first()
        try:
            models = list_local_models(provider)
        except ExternalServiceError as exc:
            return Response({'models': [], 'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'models': models})


class PromptTemplateViewSet(viewsets.ModelViewSet):
    queryset = PromptTemplate.objects.all()
    serializer_class = PromptTemplateSerializer
    permission_classes = [IsAdminWriteStaffRead]
    filterset_class = PromptTemplateFilter
    search_fields = ['name', 'code']


class GenerationRunViewSet(SchemaSafeQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """LLM call log: admins see every call, teachers the calls made by their own research runs."""

    schema_model = 'llm.GenerationRun'
    serializer_class = GenerationRunSerializer
    permission_classes = [IsTeacherOrAdmin]
    filterset_class = GenerationRunFilter
    search_fields = ['question_text', 'response_text']
    ordering_fields = ['created_at', 'latency_ms', 'total_tokens', 'estimated_cost']

    def get_queryset(self):
        return selectors.generation_runs_for_user(self.request.user)
