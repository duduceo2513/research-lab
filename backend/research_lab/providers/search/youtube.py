"""YouTube Data API — finds video lectures. Needs ``YOUTUBE_API_KEY``. The API returns titles and
descriptions only (never transcripts), so that description is the text kept for each video.

https://developers.google.com/youtube/v3/docs/search/list
"""
from __future__ import annotations

from datetime import date

from django.conf import settings

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://www.googleapis.com/youtube/v3/search'


class YouTubeProvider(SearchProvider):
    code = SourceProvider.YOUTUBE
    required_settings = ('YOUTUBE_API_KEY',)
    metadata_only = True

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        data = get_json(BASE_URL, params={
            'part': 'snippet', 'q': f'{query} lecture', 'type': 'video', 'maxResults': min(limit, 25),
            'key': settings.YOUTUBE_API_KEY})
        candidates = []
        for item in data.get('items', []):
            snippet = item.get('snippet') or {}
            video_id = (item.get('id') or {}).get('videoId')
            if not video_id:
                continue
            try:
                published = date.fromisoformat((snippet.get('publishedAt') or '')[:10])
            except ValueError:
                published = None
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.VIDEO, title=snippet.get('title') or 'Untitled',
                url=f'https://www.youtube.com/watch?v={video_id}', external_id=video_id,
                publisher=snippet.get('channelTitle', ''), published_at=published, open_access=True,
                abstract=snippet.get('description', ''), metadata={'channel': snippet.get('channelTitle'), 'transcript': False},
            ))
        return candidates
