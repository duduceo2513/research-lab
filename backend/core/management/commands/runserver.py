"""``manage.py runserver``: daphne's ASGI dev server (HTTP + WebSocket) that first marks runs left
unfinished by a previous server process as FAILED — research runs execute in background threads of
the server process, so a restart (or an autoreload) ends them."""
from daphne.management.commands.runserver import Command as DaphneRunserver
from django.db import DatabaseError


class Command(DaphneRunserver):
    def inner_run(self, *args, **options):
        from research_lab.tasks import fail_interrupted_runs

        try:
            interrupted = fail_interrupted_runs()
        except DatabaseError:  # not migrated yet: daphne will warn about it itself
            interrupted = 0
        if interrupted:
            self.stdout.write(self.style.WARNING(f'{interrupted} interrupted research run(s) marked as failed.'))
        return super().inner_run(*args, **options)
