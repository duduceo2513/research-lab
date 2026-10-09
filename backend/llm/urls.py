from django.urls import path
from rest_framework.routers import DefaultRouter

from llm import views

router = DefaultRouter()
router.register('providers', views.LLMProviderViewSet, basename='llm-provider')
router.register('configurations', views.LLMConfigurationViewSet, basename='llm-configuration')
router.register('prompt-templates', views.PromptTemplateViewSet, basename='prompt-template')
router.register('generation-runs', views.GenerationRunViewSet, basename='generation-run')

urlpatterns = [
    path('local-models/', views.LocalModelsView.as_view(), name='llm-local-models'),
    *router.urls,
]
