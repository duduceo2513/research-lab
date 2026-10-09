from django.urls import re_path

from research_lab import consumers

websocket_urlpatterns = [
    re_path(r'^ws/research-lab/runs/(?P<run_id>\d+)/$', consumers.ResearchRunConsumer.as_asgi()),
]
