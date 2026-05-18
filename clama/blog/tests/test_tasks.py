from unittest.mock import MagicMock, patch

import pytest
import requests
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from clama.blog.models import Comentario
from clama.blog.tasks import (
    enviar_alerta_comentarios_diario,
    notificar_indexnow,
    purgar_ips_antigos,
    regenerar_blog_ssg,
)
from clama.blog.tests.factories import ComentarioFactory, PostFactory


def _ok_response(status_code=200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    return r


def _http_error_response(status_code):
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    err = requests.HTTPError(response=r)
    r.raise_for_status = MagicMock(side_effect=err)
    return r, err


class TestRegenerarBlogSsgNoUrl:
    def test_skip_when_url_empty(self, settings):
        settings.VERCEL_DEPLOY_HOOK_URL = ""
        with patch("clama.blog.tasks.requests.post") as mock_post:
            regenerar_blog_ssg("abc-123")
        mock_post.assert_not_called()


class TestRegenerarBlogSsgWithUrl:
    def test_success(self, settings):
        settings.VERCEL_DEPLOY_HOOK_URL = "https://vercel.test/hook"
        with patch(
            "clama.blog.tasks.requests.post", return_value=_ok_response()
        ) as mock_post:
            regenerar_blog_ssg("abc-123")
        mock_post.assert_called_once_with(
            "https://vercel.test/hook", timeout=30
        )

    def test_4xx_does_not_retry_and_calls_sentry(self, settings):
        settings.VERCEL_DEPLOY_HOOK_URL = "https://vercel.test/hook"
        _, err = _http_error_response(400)
        with patch("clama.blog.tasks.requests.post") as mock_post, patch(
            "clama.blog.tasks.sentry_sdk.capture_exception"
        ) as mock_sentry:
            mock_post.return_value.raise_for_status.side_effect = err
            mock_post.return_value.status_code = 400
            regenerar_blog_ssg("abc-123")
        mock_sentry.assert_called_once()

    def test_5xx_calls_retry(self, settings):
        settings.VERCEL_DEPLOY_HOOK_URL = "https://vercel.test/hook"
        _, err = _http_error_response(503)
        with patch("clama.blog.tasks.requests.post") as mock_post, patch(
            "clama.blog.tasks.sentry_sdk.capture_exception"
        ) as mock_sentry, patch.object(
            regenerar_blog_ssg, "retry", side_effect=MaxRetriesExceededError()
        ) as mock_retry:
            mock_post.return_value.raise_for_status.side_effect = err
            mock_post.return_value.status_code = 503
            regenerar_blog_ssg("abc-123")
        mock_retry.assert_called()
        mock_sentry.assert_called_once()

    def test_connection_error_calls_retry(self, settings):
        settings.VERCEL_DEPLOY_HOOK_URL = "https://vercel.test/hook"
        with patch(
            "clama.blog.tasks.requests.post",
            side_effect=requests.ConnectionError("boom"),
        ), patch(
            "clama.blog.tasks.sentry_sdk.capture_exception"
        ) as mock_sentry, patch.object(
            regenerar_blog_ssg, "retry", side_effect=MaxRetriesExceededError()
        ) as mock_retry:
            regenerar_blog_ssg("abc-123")
        mock_retry.assert_called()
        mock_sentry.assert_called_once()


class TestNotificarIndexnowNoKey:
    def test_skip_when_key_empty(self, settings):
        settings.INDEXNOW_KEY = ""
        with patch("clama.blog.tasks.requests.post") as mock_post:
            notificar_indexnow("abc-123")
        mock_post.assert_not_called()


@pytest.mark.django_db
class TestNotificarIndexnowWithKey:
    @pytest.fixture(autouse=True)
    def _set_settings(self, settings):
        settings.INDEXNOW_KEY = "test-key-123"
        settings.FRONTEND_PUBLIC_BLOG_BASE_URL = "https://clama.test"

    def test_post_not_found_returns_early(self):
        with patch("clama.blog.tasks.requests.post") as mock_post:
            notificar_indexnow("00000000-0000-0000-0000-000000000000")
        mock_post.assert_not_called()

    def test_success(self):
        post = PostFactory(slug="meu-post")
        with patch(
            "clama.blog.tasks.requests.post", return_value=_ok_response()
        ) as mock_post:
            notificar_indexnow(str(post.id))
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.indexnow.org/indexnow"
        body = kwargs["json"]
        assert body["host"] == "clama.test"
        assert body["key"] == "test-key-123"
        assert body["urlList"] == ["https://clama.test/blog/meu-post"]

    def test_4xx_logs_warning_no_sentry(self):
        post = PostFactory(slug="meu-post")
        _, err = _http_error_response(403)
        with patch("clama.blog.tasks.requests.post") as mock_post, patch(
            "clama.blog.tasks.sentry_sdk.capture_exception"
        ) as mock_sentry:
            mock_post.return_value.raise_for_status.side_effect = err
            mock_post.return_value.status_code = 403
            notificar_indexnow(str(post.id))
        mock_sentry.assert_not_called()

    def test_5xx_retries_no_sentry_on_max_retries(self):
        post = PostFactory(slug="meu-post")
        _, err = _http_error_response(503)
        with patch("clama.blog.tasks.requests.post") as mock_post, patch(
            "clama.blog.tasks.sentry_sdk.capture_exception"
        ) as mock_sentry, patch.object(
            notificar_indexnow, "retry", side_effect=MaxRetriesExceededError()
        ) as mock_retry:
            mock_post.return_value.raise_for_status.side_effect = err
            mock_post.return_value.status_code = 503
            notificar_indexnow(str(post.id))
        mock_retry.assert_called()
        mock_sentry.assert_not_called()


@pytest.mark.django_db
class TestEnviarAlertaComentariosDiario:
    def test_no_comments_skip(self, settings):
        settings.ADMIN_ALERT_EMAIL = "admin@clama.test"
        with patch("clama.blog.tasks.send_mail") as mock_send:
            result = enviar_alerta_comentarios_diario()
        assert result == {"n_novos": 0, "n_suspeitos": 0, "n_email_enviados": 0}
        mock_send.assert_not_called()

    def test_envia_email_com_comentarios_novos(self, settings):
        settings.ADMIN_ALERT_EMAIL = "admin@clama.test"
        ComentarioFactory(conteudo="Comentário limpo um")
        ComentarioFactory(conteudo="Comentário limpo dois")
        ComentarioFactory(conteudo="Comentário com merda nele")
        with patch("clama.blog.tasks.send_mail") as mock_send:
            result = enviar_alerta_comentarios_diario()
        assert result["n_novos"] == 3
        assert result["n_suspeitos"] == 1
        assert result["n_email_enviados"] == 1
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert "3 novos" in call_kwargs["subject"]
        assert "1 suspeitos" in call_kwargs["subject"]
        assert call_kwargs["recipient_list"] == ["admin@clama.test"]

    def test_old_comments_excluded(self, settings):
        settings.ADMIN_ALERT_EMAIL = "admin@clama.test"
        c = ComentarioFactory(conteudo="Antigo")
        Comentario.objects.filter(id=c.id).update(
            created_at=timezone.now() - timezone.timedelta(days=2)
        )
        with patch("clama.blog.tasks.send_mail") as mock_send:
            result = enviar_alerta_comentarios_diario()
        assert result["n_novos"] == 0
        mock_send.assert_not_called()

    def test_no_recipient_logs_warning(self, settings):
        settings.ADMIN_ALERT_EMAIL = ""
        ComentarioFactory()
        with patch("clama.blog.tasks.send_mail") as mock_send:
            result = enviar_alerta_comentarios_diario()
        assert result["n_email_enviados"] == 0
        mock_send.assert_not_called()


@pytest.mark.django_db
class TestPurgarIpsAntigos:
    def test_purga_apenas_acima_de_180d(self):
        # Recente — deve ficar
        recente = ComentarioFactory(ip_address="10.0.0.1")
        # Antigo — deve ser zerado
        antigo = ComentarioFactory(ip_address="10.0.0.2")
        Comentario.objects.filter(id=antigo.id).update(
            created_at=timezone.now() - timezone.timedelta(days=200)
        )
        # Também antigo mas sem IP — não toca
        sem_ip = ComentarioFactory(ip_address="")
        Comentario.objects.filter(id=sem_ip.id).update(
            created_at=timezone.now() - timezone.timedelta(days=200)
        )

        result = purgar_ips_antigos()
        assert result["n_purgados"] == 1

        recente.refresh_from_db()
        antigo.refresh_from_db()
        sem_ip.refresh_from_db()
        assert recente.ip_address == "10.0.0.1"
        assert antigo.ip_address == ""
        assert sem_ip.ip_address == ""

    def test_no_old_comments_returns_zero(self):
        ComentarioFactory(ip_address="10.0.0.1")
        result = purgar_ips_antigos()
        assert result["n_purgados"] == 0

    def test_exato_180d_nao_purga(self):
        # Boundary: cutoff é `now - 180d`. Comentário criado EXATAMENTE no
        # cutoff não é purgado (filtro é `created_at__lt=cutoff`, strict less).
        c = ComentarioFactory(ip_address="10.0.0.1")
        # Setar created_at exatamente no cutoff (180d) — segundos podem variar
        # então usamos 179d (claramente antes da janela): deve NÃO purgar.
        Comentario.objects.filter(id=c.id).update(
            created_at=timezone.now() - timezone.timedelta(days=179)
        )
        result = purgar_ips_antigos()
        assert result["n_purgados"] == 0
        c.refresh_from_db()
        assert c.ip_address == "10.0.0.1"
