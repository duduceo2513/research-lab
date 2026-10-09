from django.urls import path
from rest_framework.routers import DefaultRouter

from research_lab import views

router = DefaultRouter()
router.register('runs', views.ResearchRunViewSet, basename='research-run')

urlpatterns = [
    path('config/', views.ConfigView.as_view(), name='research-lab-config'),
    path('settings/', views.ModuleSettingsView.as_view(), name='research-lab-settings'),
    path('settings/providers/<str:code>/test/', views.ProviderTestView.as_view(), name='research-lab-provider-test'),
    *router.urls,
]
