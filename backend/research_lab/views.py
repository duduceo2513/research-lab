from django.db import transaction
from django.db.models import Count, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import SchemaSafeQuerysetMixin
from accounts.permissions import IsAdminRole
from llm.models import GenerationRun
from research_lab import selectors
from research_lab.filters import ResearchRunFilter
from research_lab.models import ACTIVE_RUN_STATUSES, ModuleSettings, ResearchEvent
from research_lab.permissions import IsResearchLabEnabled, IsResearchLabUser
from research_lab.serializers import (AgentExecutionSerializer, AssignmentSerializer, ConfigSerializer,
                                      GeneratedLectureSerializer, ModuleSettingsSerializer,
                                      ResearchRunListSerializer, ResearchRunSerializer,
                                      ResearchSourceDetailSerializer, ResearchSourceSerializer,
                                      ToolExecutionSerializer, build_config)
from research_lab.exceptions import ProviderError
from research_lab.services import module_settings as provider_info
from research_lab.services import provider_gate, report as run_report
from research_lab.services import events as research_events
from research_lab.services import workspace
from research_lab.services.lecture_format import render_docx


class ConfigView(APIView):
    """Readable by any authenticated user (not staff-gated): lets the frontend hide the Research
    Lab nav link and populate its create-run form without a staff-only call."""

    @extend_schema(responses=ConfigSerializer)
    def get(self, request):
        return Response(ConfigSerializer(build_config()).data)


class ModuleSettingsView(APIView):
    """Admin-only: which search providers the module uses and its default LLM tier (Local / Cloud
    / Hybrid). Read-only info derived from this (``provider_statuses()``) is also exposed to any
    authenticated user via ``ConfigView``, so the create-run form can show it without this gate."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses=ModuleSettingsSerializer)
    def get(self, request):
        return Response(ModuleSettingsSerializer(ModuleSettings.load()).data)

    @extend_schema(request=ModuleSettingsSerializer, responses=ModuleSettingsSerializer)
    def patch(self, request):
        serializer = ModuleSettingsSerializer(ModuleSettings.load(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProviderTestView(APIView):
    """Admin-only "test connection": one tiny real search against a single source, so Settings can show
    whether it answers (and why not). Records the outcome as that source's health."""

    permission_classes = [IsAdminRole]

    @extend_schema(request=None, responses=dict)
    def post(self, request, code):
        provider = next((p for p in provider_info.all_providers() if str(p.code) == code.upper()), None)
        if provider is None:
            raise Http404('Unknown source.')
        if provider.configured():
            try:
                provider.search('hash tables', limit=1)
                provider_gate.record_health(provider.code, True)
            except ProviderError as exc:
                provider_gate.record_health(provider.code, False, str(exc))
        return Response(provider_info.provider_status(provider))


class ResearchRunViewSet(SchemaSafeQuerysetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.CreateModelMixin, viewsets.GenericViewSet):
    """No update/delete: a run's inputs are fixed once started; ``cancel`` is the only mutation."""

    schema_model = 'research_lab.ResearchRun'
    permission_classes = [IsResearchLabEnabled, IsResearchLabUser]
    filterset_class = ResearchRunFilter
    search_fields = ['topic', 'description']
    ordering_fields = ['created_at', 'status']

    def get_queryset(self):
        return selectors.runs_for_user(self.request.user)

    def get_serializer_class(self):
        return ResearchRunSerializer if self.action in ('create', 'retrieve') else ResearchRunListSerializer

    def create(self, request, *args, **kwargs):
        serializer = ResearchRunSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            run = serializer.save()

            def _dispatch() -> None:
                from research_lab.tasks import dispatch

                dispatch(run.pk)

            transaction.on_commit(_dispatch)
        return Response(ResearchRunSerializer(run, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cooperative cancellation: the orchestrator checks this flag between agent steps (there
        is no clean way to hard-kill a worker thread mid-step without risking an inconsistent run)."""
        run = self.get_object()
        if run.status not in ACTIVE_RUN_STATUSES:
            return Response({'detail': 'This run has already finished.'}, status=status.HTTP_409_CONFLICT)
        run.cancel_requested = True
        run.save(update_fields=['cancel_requested'])
        return Response(ResearchRunSerializer(run, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def sources(self, request, pk=None):
        """The materials found by this run. Optional filters: ``provider``, ``source_type``,
        ``document_format`` (PDF/PPTX/DOCX/HTML/TXT), ``downloaded=1`` (an original file is stored) and
        ``duplicates=1`` (include duplicates, which are hidden otherwise)."""
        run = self.get_object()
        queryset = selectors.sources_for_user(request.user).filter(run_id=pk)
        if run.mode == 'SEARCH':  # no scores to rank by: group by source, in the order they were found
            queryset = queryset.order_by('provider', 'id')
        params = request.query_params
        if params.get('provider'):
            queryset = queryset.filter(provider=params['provider'].upper())
        if params.get('source_type'):
            queryset = queryset.filter(source_type=params['source_type'].upper())
        if params.get('document_format'):
            queryset = queryset.filter(document__content_type=params['document_format'].upper())
        if params.get('downloaded') in ('1', 'true'):
            queryset = queryset.exclude(document__file='')
        if params.get('duplicates') not in ('1', 'true') and params.get('include_duplicates') is None:
            queryset = queryset.filter(is_duplicate=False)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(ResearchSourceSerializer(page, many=True).data)

    def _source(self, request, pk, source_id):
        self.get_object()
        source = selectors.sources_for_user(request.user).filter(run_id=pk, pk=source_id).first()
        if source is None:
            raise Http404('No such material in this run.')
        return source

    @action(detail=True, methods=['get'], url_path=r'sources/(?P<source_id>\d+)')
    def source_detail(self, request, pk=None, source_id=None):
        """One material with its complete text (API full text, or text extracted from the document)."""
        return Response(ResearchSourceDetailSerializer(self._source(request, pk, source_id)).data)

    @action(detail=True, methods=['get'], url_path=r'sources/(?P<source_id>\d+)/file')
    def source_file(self, request, pk=None, source_id=None):
        """The original downloaded document. PDFs are served inline so the browser can show them;
        everything else (and ``?download=1``) as an attachment."""
        document = getattr(self._source(request, pk, source_id), 'document', None)
        if document is None or not document.file:
            raise Http404('No file was downloaded for this material.')
        inline = document.content_type == 'PDF' and request.query_params.get('download') not in ('1', 'true')
        try:
            handle = document.file.open('rb')
        except FileNotFoundError as exc:
            raise Http404('The stored file is missing.') from exc
        response = FileResponse(handle, as_attachment=not inline, filename=document.file_name or 'document',
                                content_type=document.mime_type or 'application/octet-stream')
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    @action(detail=True, methods=['get'])
    def context(self, request, pk=None):
        """All collected text of this search as one block, ready to hand to an LLM / RAG pipeline later.
        ``?download=1`` returns it as a .txt file instead of JSON. Duplicates and empty documents are left out."""
        run = self.get_object()
        sources = (selectors.sources_for_user(request.user).filter(run_id=pk, is_duplicate=False)
                   .order_by('provider', 'id'))
        blocks, used = [], 0
        for source in sources:
            document = getattr(source, 'document', None)
            text = (document.text if document and document.text else source.abstract) or ''
            if not text.strip():
                continue
            used += 1
            header = [f'### [{used}] {source.title}', f'Source: {source.get_provider_display()} | Type: {source.get_source_type_display()}']
            if source.url:
                header.append(f'URL: {source.url}')
            if source.authors:
                header.append('Authors: ' + ', '.join(source.authors[:8]))
            blocks.append('\n'.join(header) + '\n\n' + text.strip())
        body = f'TOPIC: {run.topic}\nMATERIALS: {used}\n\n' + '\n\n' + ('\n\n' + '=' * 80 + '\n\n').join(blocks)
        if request.query_params.get('download') in ('1', 'true'):
            response = HttpResponse(body, content_type='text/plain; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{slugify(run.topic) or "materials"}-context.txt"'
            return response
        return Response({'run': run.pk, 'topic': run.topic, 'materials': used, 'characters': len(body), 'text': body})

    @action(detail=True, methods=['get'])
    def agents(self, request, pk=None):
        self.get_object()
        page = self.paginate_queryset(selectors.agent_executions_for_user(request.user).filter(run_id=pk))
        return self.get_paginated_response(AgentExecutionSerializer(page, many=True).data)

    @action(detail=True, methods=['get'])
    def tools(self, request, pk=None):
        self.get_object()
        page = self.paginate_queryset(selectors.tool_executions_for_user(request.user).filter(run_id=pk))
        return self.get_paginated_response(ToolExecutionSerializer(page, many=True).data)

    @action(detail=True, methods=['get'])
    def assignment(self, request, pk=None):
        run = self.get_object()
        assignment = getattr(run, 'assignment', None)
        if assignment is None:
            return Response({'detail': 'No assignment has been generated for this run yet.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(AssignmentSerializer(assignment).data)

    @action(detail=True, methods=['get'])
    def lecture(self, request, pk=None):
        """The latest version of the generated lecture (revisions are kept, never overwritten —
        see ``GeneratedLecture``), so this always reflects the most recent draft/approval."""
        self.get_object()
        lecture = selectors.lectures_for_user(request.user).filter(run_id=pk).order_by('-version').first()
        if lecture is None:
            return Response({'detail': 'No lecture has been generated for this run yet.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(GeneratedLectureSerializer(lecture).data)

    @action(detail=True, methods=['get'], url_path='lecture/export')
    def export_lecture(self, request, pk=None):
        self.get_object()
        lecture = selectors.lectures_for_user(request.user).filter(run_id=pk).order_by('-version').first()
        if lecture is None:
            return Response({'detail': 'No lecture has been generated for this run yet.'},
                            status=status.HTTP_404_NOT_FOUND)
        # Deliberately not "format": that query param name is reserved by DRF's own content
        # negotiation (URL_FORMAT_OVERRIDE) and would 404 before this method ever runs.
        fmt = request.query_params.get('export_format', 'md').lower()
        filename = slugify(lecture.title) or 'lecture'

        if fmt == 'docx':
            content = render_docx(title=lecture.title, learning_objectives=lecture.learning_objectives,
                                  content=lecture.content_json)
            response = HttpResponse(
                content, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="{filename}.docx"'
            return response

        ext = 'txt' if fmt == 'txt' else 'md'
        response = HttpResponse(lecture.plain_text, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}.{ext}"'
        return response

    @action(detail=True, methods=['get'])
    def events(self, request, pk=None):
        """The persisted event stream (oldest first). ``after_id`` resumes after the last event the
        client has seen — used on page load and after a WebSocket reconnect."""
        self.get_object()
        try:
            after_id = int(request.query_params.get('after_id', 0))
            limit = min(int(request.query_params.get('limit', 1000)), 2000)
        except ValueError:
            return Response({'detail': 'after_id and limit must be integers.'}, status=status.HTTP_400_BAD_REQUEST)
        rows = ResearchEvent.objects.filter(run_id=pk, id__gt=after_id).order_by('id')[:limit]
        return Response([research_events.serialize(event) for event in rows])

    @action(detail=True, methods=['get'])
    def workspace(self, request, pk=None):
        """Server-computed snapshot of the whole Agent Workspace (agents, research state, metrics)."""
        return Response(workspace.build(self.get_object()))

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """The run's load report: per-agent LLM + tool calls and shares (the 40% rule), totals and
        deliverables. ``?as=markdown`` returns it as a .md file, ``?as=json`` as a .json file."""
        data = run_report.build_report(self.get_object())
        kind = request.query_params.get('as')
        if kind in ('markdown', 'md'):
            response = HttpResponse(run_report.render_markdown(data), content_type='text/markdown; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="run-{pk}-report.md"'
            return response
        if kind == 'json':
            import json

            response = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type='application/json')
            response['Content-Disposition'] = f'attachment; filename="run-{pk}-report.json"'
            return response
        return Response(data)

    @action(detail=True, methods=['get'])
    def metrics(self, request, pk=None):
        run = self.get_object()
        sources = selectors.sources_for_user(request.user).filter(run_id=pk)
        agent_calls = list(selectors.agent_executions_for_user(request.user).filter(run_id=pk)
                           .values('agent').annotate(count=Count('id')))
        total_agent_calls = sum(row['count'] for row in agent_calls) or 1
        # Load as the brief defines it: share of all LLM + tool calls, not of agent runs.
        shares, _ = run_report.load_shares(run)
        max_agent_load = max((row['pct'] for row in shares), default=0.0) / 100
        tool_calls = selectors.tool_executions_for_user(request.user).filter(run_id=pk).count()
        usage = GenerationRun.objects.filter(metadata__run_id=run.pk).aggregate(
            total_tokens=Sum('total_tokens'), estimated_cost=Sum('estimated_cost'))

        execution_seconds = None
        if run.started_at:
            end = run.finished_at or run.updated_at
            execution_seconds = (end - run.started_at).total_seconds()

        return Response({
            'sources_found': sources.count(),
            'unique_sources': sources.filter(is_duplicate=False).count(),
            'documents_analyzed': sources.filter(document__isnull=False).count(),
            'accepted': sources.filter(decision='ACCEPT').count(),
            'rejected': sources.filter(decision='REJECT').count(),
            'needs_review': sources.filter(decision='REVIEW').count(),
            'agent_calls_by_agent': {row['agent']: row['count'] for row in agent_calls},
            'agent_calls_total': total_agent_calls if agent_calls else 0,
            'max_agent_load_pct': round(max_agent_load * 100, 1),
            'tool_calls_total': tool_calls,
            'execution_time_seconds': execution_seconds,
            'total_tokens': usage['total_tokens'],
            'estimated_cost': usage['estimated_cost'],
            'revision_count': run.revision_count,
            'status': run.status,
        })
