from unittest.mock import MagicMock

import pytest
from django.test import RequestFactory

from clama.blog.middleware import BuildTokenAuthMiddleware


def _run_middleware(meta_headers: dict):
    rf = RequestFactory()
    request = rf.get("/api/blog/public/posts/", **meta_headers)
    get_response = MagicMock(return_value="ok")
    mw = BuildTokenAuthMiddleware(get_response)
    mw(request)
    return request


class TestBuildTokenAuthMiddleware:
    def test_header_correto_seta_flag_true(self, settings):
        settings.BUILD_API_TOKEN = "secret-build-token"
        request = _run_middleware({"HTTP_X_BUILD_TOKEN": "secret-build-token"})
        assert request.is_build_token is True

    def test_header_errado_seta_flag_false(self, settings):
        settings.BUILD_API_TOKEN = "secret-build-token"
        request = _run_middleware({"HTTP_X_BUILD_TOKEN": "wrong-token"})
        assert request.is_build_token is False

    def test_sem_header_seta_flag_false(self, settings):
        settings.BUILD_API_TOKEN = "secret-build-token"
        request = _run_middleware({})
        assert request.is_build_token is False

    def test_token_vazio_em_settings_nunca_true(self, settings):
        # Defesa: mesmo com header válido, se settings.BUILD_API_TOKEN é
        # vazio, flag NUNCA é True (evita ataque de header=""+config="").
        settings.BUILD_API_TOKEN = ""
        request = _run_middleware({"HTTP_X_BUILD_TOKEN": ""})
        assert request.is_build_token is False

    def test_ambos_vazios_seta_flag_false(self, settings):
        settings.BUILD_API_TOKEN = ""
        request = _run_middleware({})
        assert request.is_build_token is False

    def test_get_response_e_chamado(self, settings):
        settings.BUILD_API_TOKEN = "x"
        rf = RequestFactory()
        request = rf.get("/")
        get_response = MagicMock(return_value="passed-through")
        mw = BuildTokenAuthMiddleware(get_response)
        result = mw(request)
        assert result == "passed-through"
        get_response.assert_called_once_with(request)
