"""Prints (or saves) the load report of a Research Lab run: LLM + tool calls per agent and each agent's
share of the total — the evidence the project brief asks for ("no agent above 40%, confirmed by logs").

    python manage.py research_report 17
    python manage.py research_report 17 --markdown run-17.md --json run-17.json
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from research_lab.models import ResearchRun
from research_lab.services import report


class Command(BaseCommand):
    help = 'Show the per-agent call/load report of one Research Lab run.'

    def add_arguments(self, parser):
        parser.add_argument('run_id', type=int)
        parser.add_argument('--markdown', help='write the report to this .md file')
        parser.add_argument('--json', help='write the raw report to this .json file')

    def handle(self, *args, run_id, markdown=None, json=None, **options):  # noqa: A002 - CLI flag name
        run = ResearchRun.objects.filter(pk=run_id).first()
        if run is None:
            raise CommandError(f'Run {run_id} does not exist.')
        data = report.build_report(run)
        text = report.render_markdown(data)
        self.stdout.write(text)
        if markdown:
            Path(markdown).write_text(text, encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'Saved {markdown}'))
        if json:
            Path(json).write_text(__import__('json').dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'Saved {json}'))
