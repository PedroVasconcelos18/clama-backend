"""Monitoramento de desindexação silenciosa (Story 5.10).

🔴 Condição de aceitação do ADR-03. Delegar o SEO técnico do domínio inteiro ao
WordPress é aceitável **apenas** com este monitoramento.

O interruptor vigiado: "Search Engine Visibility" no WordPress escreve
`Disallow: /` no robots.txt — que, sob a ADR-03, é o de `clama.me`. Um clique
tira a landing, a `/conta` e o fluxo de pedido do índice.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from clama.blog.tasks import monitorar_seo_do_dominio

ROBOTS_SAUDAVEL = """User-agent: *
Allow: /blog/
Disallow: /admin/
Disallow: /api/

Sitemap: https://clama.me/sitemap.xml
"""

ROBOTS_QUE_BLOQUEIA_TUDO = """User-agent: *
Disallow: /
"""


@pytest.fixture
def base(settings):
    settings.FRONTEND_PUBLIC_BLOG_BASE_URL = "https://clama.me"
    settings.INDEXNOW_KEY = ""


def resposta(texto="", status=200, headers=None):
    r = Mock(spec=requests.Response)
    r.status_code = status
    r.text = texto
    r.headers = headers or {}
    return r


def respostas(**por_caminho):
    """Devolve um `side_effect` que responde por sufixo de URL."""
    padrao = por_caminho.pop("padrao", resposta("<html></html>"))

    def escolher(url, **_):
        for sufixo, r in por_caminho.items():
            if url.endswith(sufixo.replace("_", ".").replace("..", "/")):
                return r
        for sufixo, r in por_caminho.items():
            if sufixo.strip("/") in url:
                return r
        return padrao

    return escolher


class TestRobots:
    def test_disallow_barra_dispara_alerta(self, base):
        # AC1, e é o cenário que a story inteira existe para pegar.
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{"robots.txt": resposta(ROBOTS_QUE_BLOQUEIA_TUDO)}
            )
            with patch("clama.blog.tasks.sentry_sdk") as sentry:
                r = monitorar_seo_do_dominio()

        tipos = {p["tipo"] for p in r["problemas"]}
        assert "robots_bloqueia_tudo" in tipos
        assert sentry.capture_message.call_args.kwargs["level"] == "error"

    def test_robots_saudavel_nao_alerta(self, base):
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(**{"robots.txt": resposta(ROBOTS_SAUDAVEL)})
            with patch("clama.blog.tasks.sentry_sdk") as sentry:
                r = monitorar_seo_do_dominio()

        assert r["problemas"] == []
        sentry.capture_message.assert_not_called()

    def test_disallow_admin_nao_e_confundido_com_disallow_tudo(self, base):
        # `Disallow: /admin/` **contém** a substring `Disallow: /`. Comparar
        # por substring produziria alarme em todo robots.txt saudável — e um
        # monitoramento que grita sempre é um monitoramento desligado.
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(**{"robots.txt": resposta(ROBOTS_SAUDAVEL)})
            r = monitorar_seo_do_dominio()

        assert not any(p["tipo"] == "robots_bloqueia_tudo" for p in r["problemas"])

    def test_indisponivel_e_distinto_de_conteudo_errado(self, base):
        # AC3: as causas e as respostas são diferentes. 503 é a origem caindo;
        # `Disallow: /` é alguém que clicou.
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(**{"robots.txt": resposta("", status=503)})
            r = monitorar_seo_do_dominio()

        tipos = {p["tipo"] for p in r["problemas"]}
        assert "robots_indisponivel" in tipos
        assert "robots_bloqueia_tudo" not in tipos

    def test_erro_de_rede_nao_derruba_a_task(self, base):
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = requests.Timeout("caiu")
            r = monitorar_seo_do_dominio()

        assert any(p["tipo"] == "robots_indisponivel" for p in r["problemas"])


class TestSitemapENoindex:
    def test_sitemap_fora_do_ar_alerta(self, base):
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("", status=404),
                }
            )
            r = monitorar_seo_do_dominio()

        assert any(p["tipo"] == "sitemap_indisponivel" for p in r["problemas"])

    def test_noindex_no_header_e_detectado(self, base):
        # AC4 — os dois caminhos são independentes. Checar só a meta deixaria
        # metade do risco invisível.
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("<urlset/>"),
                    "/blog": resposta(
                        "<html></html>", headers={"X-Robots-Tag": "noindex, follow"}
                    ),
                }
            )
            r = monitorar_seo_do_dominio()

        assert any(p["tipo"] == "noindex_no_header" for p in r["problemas"])

    def test_noindex_na_meta_e_detectado(self, base):
        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("<urlset/>"),
                    "/blog": resposta(
                        '<html><head><meta name="robots" content="noindex,follow">'
                        "</head></html>"
                    ),
                }
            )
            r = monitorar_seo_do_dominio()

        assert any(p["tipo"] == "noindex_na_meta" for p in r["problemas"])


class TestChaveIndexNow:
    def test_sem_chave_configurada_nao_vira_ruido(self, base, settings):
        # Ausência de recurso não é problema. Alertar aqui produziria uma
        # notificação a cada 30 minutos para sempre.
        settings.INDEXNOW_KEY = ""

        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(**{"robots.txt": resposta(ROBOTS_SAUDAVEL)})
            r = monitorar_seo_do_dominio()

        assert not any("indexnow" in p["tipo"] for p in r["problemas"])

    def test_chave_inacessivel_alerta(self, base, settings):
        # AC5. Rotacionar a chave quebra o FR48 **em silêncio** — o
        # vercel.json aponta para a velha, o Bing devolve 403, e nada mais
        # sinaliza. Esta é a única checagem que detecta.
        settings.INDEXNOW_KEY = "abc123"

        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("<urlset/>"),
                    "abc123.txt": resposta("", status=404),
                }
            )
            r = monitorar_seo_do_dominio()

        problema = next(p for p in r["problemas"] if "indexnow" in p["tipo"])
        assert "sem aviso" in problema["detalhe"]

    def test_chave_divergente_alerta(self, base, settings):
        # O arquivo responde 200 mas com outra chave: é o sintoma de
        # regeneração pelo plugin.
        settings.INDEXNOW_KEY = "abc123"

        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("<urlset/>"),
                    "abc123.txt": resposta("outra-chave-qualquer"),
                }
            )
            r = monitorar_seo_do_dominio()

        assert any(p["tipo"] == "chave_indexnow_divergente" for p in r["problemas"])

    def test_chave_correta_nao_alerta(self, base, settings):
        settings.INDEXNOW_KEY = "abc123"

        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = respostas(
                **{
                    "robots.txt": resposta(ROBOTS_SAUDAVEL),
                    "sitemap.xml": resposta("<urlset/>"),
                    "abc123.txt": resposta("abc123"),
                }
            )
            r = monitorar_seo_do_dominio()

        assert r["problemas"] == []


class TestAgendamento:
    def test_esta_no_beat_com_a_justificativa_escrita(self, settings):
        entrada = settings.CELERY_BEAT_SCHEDULE["blog-monitorar-seo-do-dominio"]
        assert entrada["task"] == "clama.blog.tasks.monitorar_seo_do_dominio"

        from pathlib import Path

        texto = (Path(settings.BASE_DIR) / "config" / "settings" / "base.py").read_text(
            encoding="utf-8"
        )
        assert "condição de aceitação do ADR-03" in texto

    def test_um_alerta_por_execucao_e_nao_um_por_problema(self, base, settings):
        # Quatro notificações para uma causa só treinam quem recebe a ignorar.
        settings.INDEXNOW_KEY = "abc123"

        with patch("clama.blog.tasks.requests.get") as get:
            get.side_effect = requests.Timeout("tudo caiu")
            with patch("clama.blog.tasks.sentry_sdk") as sentry:
                r = monitorar_seo_do_dominio()

        assert len(r["problemas"]) > 1
        sentry.capture_message.assert_called_once()


class TestDiffDeUrls:
    """Story 5.9 — o diff compara URL completa, não slug."""

    def _rodar(self, **opcoes):
        from io import StringIO

        from django.core.management import call_command

        saida = StringIO()
        call_command(
            "diff_de_urls_do_blog",
            stdout=saida,
            stderr=saida,
            base="https://clama.me",
            **opcoes,
        )
        return saida.getvalue()

    @pytest.mark.django_db
    def test_sem_divergencia_libera(self):
        from clama.blog.models import PostStatus
        from clama.blog.tests.factories import PostEspelhoFactory, PostFactory

        PostFactory(slug="post-1", status=PostStatus.PUBLICADO)
        PostEspelhoFactory(slug="post-1")

        assert "Nenhuma URL some no cutover" in self._rodar()

    @pytest.mark.django_db
    def test_url_que_some_e_reportada_e_bloqueia(self):
        # AC5: cada URL que some é um 404 no que já está indexado.
        from clama.blog.models import PostStatus
        from clama.blog.tests.factories import PostFactory

        PostFactory(slug="post-orfao", status=PostStatus.PUBLICADO)

        saida = self._rodar()

        assert "/blog/post-orfao" in saida
        assert "DIVERGÊNCIA" in saida

    @pytest.mark.django_db
    def test_rascunho_do_espelho_nao_conta_como_divergencia(self):
        # Rascunho não responde 200 em lugar nenhum; incluí-lo produziria
        # divergência falsa e treinaria a ignorar o relatório.
        from clama.blog.models import PostEspelhoStatus, PostStatus
        from clama.blog.tests.factories import PostEspelhoFactory, PostFactory

        PostFactory(slug="post-1", status=PostStatus.PUBLICADO)
        PostEspelhoFactory(slug="post-1")
        PostEspelhoFactory(slug="rascunho-wp", status=PostEspelhoStatus.RASCUNHO)

        saida = self._rodar()

        assert "rascunho-wp" not in saida
        assert "Nenhuma URL some no cutover" in saida

    @pytest.mark.django_db
    def test_gera_a_lista_para_o_gate_da_6_5(self):
        # AC4.
        import json
        import tempfile
        from pathlib import Path

        from clama.blog.models import PostStatus
        from clama.blog.tests.factories import PostEspelhoFactory, PostFactory

        PostFactory(slug="post-1", status=PostStatus.PUBLICADO)
        PostEspelhoFactory(slug="post-1")

        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "urls.json"
            self._rodar(saida_json=str(destino))
            dados = json.loads(destino.read_text(encoding="utf-8"))

        assert "https://clama.me/blog/post-1" in dados["iguais"]
        assert dados["some_no_cutover"] == []
