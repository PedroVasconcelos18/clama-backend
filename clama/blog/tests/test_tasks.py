from unittest.mock import MagicMock, patch

import pytest
import requests
from celery.exceptions import MaxRetriesExceededError

from clama.blog.tasks import notificar_indexnow, regenerar_blog_ssg
from clama.blog.tests.factories import PostFactory


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
