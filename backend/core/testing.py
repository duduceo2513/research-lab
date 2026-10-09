"""Shared helpers for the test-suite (factories, fakes, temporary media)."""
from __future__ import annotations

import io
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from llm.models import LLMConfiguration, LLMProvider, ProviderCode
from llm.providers import factory
from llm.providers.base import BaseLLMProvider, GenerationRequest, GenerationResult, HealthStatus, StreamEvent

PASSWORD = 'S3cure-pass-123'
_counter = 0


def _n() -> int:
    global _counter
    _counter += 1
    return _counter


# -- users ---------------------------------------------------------------------
def make_user(role: str = UserRole.STUDENT, email: str | None = None, **extra) -> User:
    email = email or f'{role.lower()}{_n()}@example.com'
    if role == UserRole.ADMIN:
        return User.objects.create_superuser(email=email, password=PASSWORD, **extra)
    return User.objects.create_user(email=email, password=PASSWORD, role=role, **extra)


def make_teacher(**kw) -> User:
    return make_user(UserRole.TEACHER, **kw)


def make_student(**kw) -> User:
    return make_user(UserRole.STUDENT, **kw)


def make_admin(**kw) -> User:
    return make_user(UserRole.ADMIN, **kw)


def api_client(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


# -- files ---------------------------------------------------------------------------------
def pdf_bytes(pages: list[str]) -> bytes:
    """A minimal, valid multi-page PDF with real extractable text (no third-party writer needed)."""
    objects: list[bytes] = []
    n_pages = len(pages)
    kids = ' '.join(f'{3 + i * 2} 0 R' for i in range(n_pages))
    objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>'.encode())
    font_obj = 3 + n_pages * 2
    for i, text in enumerate(pages):
        content_id = 4 + i * 2
        objects.append(
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R '
            f'/Resources << /Font << /F1 {font_obj} 0 R >> >> >>'.encode())
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
        objects.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f'{i} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = out.tell()
    out.write(f'xref\n0 {len(objects) + 1}\n'.encode() + b'0000000000 65535 f \n')
    for off in offsets:
        out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


# -- LLM fakes -----------------------------------------------------------------------------
class FakeLLMProvider(BaseLLMProvider):
    """Deterministic provider: echoes a canned answer, streams it word by word."""

    answer = 'Photosynthesis converts light into chemical energy [1].'
    fail_with: Exception | None = None
    requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResult:
        type(self).requests.append(request)
        if self.fail_with:
            raise self.fail_with
        return GenerationResult(text=self.answer, input_tokens=100, output_tokens=20, finish_reason='stop',
                                model=self.model)

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        type(self).requests.append(request)
        if self.fail_with:
            raise self.fail_with
        for word in self.answer.split(' '):
            yield StreamEvent(delta=word + ' ')
        yield StreamEvent(final=GenerationResult(text=self.answer, input_tokens=100, output_tokens=20,
                                                 finish_reason='stop', model=self.model))

    def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, latency_ms=1)


@contextmanager
def fake_llm(answer: str | None = None, fail_with: Exception | None = None):
    """Route every provider code to ``FakeLLMProvider`` for the duration of the block."""
    attrs = {'answer': answer or FakeLLMProvider.answer, 'fail_with': fail_with, 'requests': []}
    with mock.patch.multiple(FakeLLMProvider, **attrs), \
            mock.patch.dict(factory._REGISTRY, {code: FakeLLMProvider for code in ProviderCode.values}):
        yield FakeLLMProvider


def make_llm_config(code: str = ProviderCode.LOCAL, *, default: bool = True, **kw) -> LLMConfiguration:
    n = _n()
    provider, _ = LLMProvider.objects.get_or_create(
        display_name=f'{code} provider', defaults={'code': code, 'secret_env_name': None})
    return LLMConfiguration.objects.create(
        provider=provider, name=kw.pop('name', f'config {n}'), model_name=kw.pop('model_name', 'fake-model'),
        is_default=default, metadata=kw.pop('metadata', {'pricing': {'input_per_1m': 1.0, 'output_per_1m': 2.0}}), **kw)


# -- test base classes ---------------------------------------------------------------------
class MediaMixin:
    """Points MEDIA_ROOT at a throw-away directory."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix='research_lab_test_media_')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)


class BaseTestCase(MediaMixin, TestCase):
    pass


class BaseTransactionTestCase(MediaMixin, TransactionTestCase):
    pass
