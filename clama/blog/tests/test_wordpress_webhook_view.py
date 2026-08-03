"""View do webhook e sincronização do espelho (Stories 3.2 e 3.3)."""

import hashlib
import hmac
from unittest.mock import patch

import pytest

from clama.blog.models import PostEspelho, PostEspelhoStatus
from clama.blog.services.wordpress_webhook import status_efetivo, traduzir_status
from clama.blog.tasks import sincronizar_post_espelho
from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider

SEGREDO = "segredo-de-teste-do-webhook"
URL = "/api/webhooks/wordpress/"
TIPO_FORM = "application/x-www-form-urlencoded"


@pytest.fixture
def com_segredo(settings):
    settings.WORDPRESS_WEBHOOK_SECRET = SEGREDO
    return SEGREDO


def corpo(**campos) -> str:
    from urllib.parse import urlencode

    base = {
        "evento_id": "evt-1",
        "tipo": "post_publicado",
        "wp_post_id": "7",
        "slug": "oracao-da-manha",
        "titulo": "Oração da manhã",
        "status": "publish",
        "url": "https://clama.me/blog/oracao-da-manha",
        "published_at": "2026-08-03T10:00:00+00:00",
    }
    base.update(campos)
    return urlencode(base)


def postar(client, texto: str):
    return client.post(
        URL,
        data=texto,
        content_type=TIPO_FORM,
        HTTP_X_CLAMA_SIGNATURE=hmac.new(
            SEGREDO.encode(), texto.encode(), hashlib.sha256
        ).hexdigest(),
    )


class TestView:
    def test_evento_valido_responde_200_e_enfileira(
        self, client, db, com_segredo, django_capture_on_commit_callbacks
    ):
        # AC6: nunca processa síncrono. O WordPress não pode ficar esperando
        # o Clama escrever no banco.
        #
        # `django_capture_on_commit_callbacks` é necessário porque o teste roda
        # numa transação que sofre rollback — sem ele o `on_commit` nunca
        # dispara e o teste passaria sem provar o enfileiramento.
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay") as espiao:
            with django_capture_on_commit_callbacks(execute=True):
                resposta = postar(client, corpo())

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "ok"}
        espiao.assert_called_once()

    def test_o_corpo_e_lido_como_form_encoded(self, client, db, com_segredo):
        # AC4. O `wp_remote_post` do PHP manda form-encoded por default;
        # assumir JSON daria 400 em todo evento legítimo.
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay"):
            postar(client, corpo(titulo="Título com acento"))

        registro = WebhookEvento.objects.get(external_event_id="evt-1")
        assert registro.payload["titulo"] == "Título com acento"
        assert registro.provider == WebhookProvider.WORDPRESS

    def test_payload_sem_evento_id_devolve_400(self, client, db, com_segredo):
        from urllib.parse import urlencode

        texto = urlencode({"tipo": "post_publicado", "wp_post_id": "7"})

        assert postar(client, texto).status_code == 400
        assert WebhookEvento.objects.count() == 0

    def test_evento_desconhecido_e_ignorado_com_200(self, client, db, com_segredo):
        # 200 e não erro: devolver 4xx/5xx faria o WordPress retriar para
        # sempre um evento que nunca vai nos interessar.
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay") as espiao:
            resposta = postar(client, corpo(tipo="comentario_aprovado"))

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "ignored"}
        espiao.assert_not_called()

        registro = WebhookEvento.objects.get(external_event_id="evt-1")
        assert registro.status == WebhookEventoStatus.IGNORADO


class TestIdempotencia:
    def test_entrega_dupla_nao_reprocessa(self, client, db, com_segredo):
        # AC5. O WordPress retria; o segundo POST não pode virar segunda task.
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay"):
            postar(client, corpo())

        WebhookEvento.objects.filter(external_event_id="evt-1").update(
            status=WebhookEventoStatus.PROCESSADO
        )

        with patch("clama.blog.tasks.sincronizar_post_espelho.delay") as espiao:
            resposta = postar(client, corpo())

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "already_processed"}
        espiao.assert_not_called()
        assert WebhookEvento.objects.count() == 1

    def test_evento_em_erro_e_reprocessavel(
        self, client, db, com_segredo, django_capture_on_commit_callbacks
    ):
        # `RECEBIDO`/`ERRO` não são terminais: se o Clama devolveu 500, o
        # reenvio precisa realmente reprocessar, senão o evento se perde.
        with patch("clama.blog.tasks.sincronizar_post_espelho.delay"):
            postar(client, corpo())

        WebhookEvento.objects.filter(external_event_id="evt-1").update(
            status=WebhookEventoStatus.ERRO
        )

        with patch("clama.blog.tasks.sincronizar_post_espelho.delay") as espiao:
            with django_capture_on_commit_callbacks(execute=True):
                resposta = postar(client, corpo())

        assert resposta.json() == {"status": "ok"}
        espiao.assert_called_once()

    def test_efeito_de_duas_entregas_e_igual_ao_de_uma(self, client, db, com_segredo):
        # A parte do AC5 que importa de verdade: não é só "não reprocessa",
        # é "o espelho fica idêntico".
        for _ in range(2):
            registro, _criado = WebhookEvento.objects.try_register(
                provider=WebhookProvider.WORDPRESS,
                external_event_id="evt-dup",
                event_type="post_publicado",
                payload={
                    "wp_post_id": "9",
                    "slug": "post-x",
                    "titulo": "Post X",
                    "status": "publish",
                },
            )
            registro.status = WebhookEventoStatus.RECEBIDO
            registro.save(update_fields=["status"])
            sincronizar_post_espelho(str(registro.id))

        assert PostEspelho.objects.filter(wp_post_id=9).count() == 1
        assert WebhookEvento.objects.filter(external_event_id="evt-dup").count() == 1


@pytest.mark.django_db
class TestSincronizacao:
    def _evento(self, **payload):
        base = {
            "wp_post_id": "11",
            "slug": "post-teste",
            "titulo": "Post teste",
            "status": "publish",
            "url": "https://clama.me/blog/post-teste",
            "published_at": "2026-08-03T10:00:00+00:00",
        }
        base.update(payload)
        tipo = base.pop("tipo", "post_publicado")
        # O id precisa distinguir também o TIPO: dois eventos do mesmo post
        # com o mesmo id seriam a mesma entrega, e o segundo curto-circuitaria
        # como já processado — que é justamente o que não se quer testar aqui.
        registro, _ = WebhookEvento.objects.try_register(
            provider=WebhookProvider.WORDPRESS,
            external_event_id=f"evt-{base['wp_post_id']}-{base['status']}-{tipo}",
            event_type=tipo,
            payload=base,
        )
        return registro

    def test_cria_o_espelho_com_todos_os_campos(self):
        evento = self._evento()

        sincronizar_post_espelho(str(evento.id))

        espelho = PostEspelho.objects.get(wp_post_id=11)
        assert espelho.slug == "post-teste"
        assert espelho.titulo == "Post teste"
        assert espelho.status == PostEspelhoStatus.PUBLICADO
        assert espelho.url == "https://clama.me/blog/post-teste"
        assert espelho.published_at is not None

        evento.refresh_from_db()
        assert evento.status == WebhookEventoStatus.PROCESSADO

    def test_atualizacao_nao_duplica_linha(self):
        sincronizar_post_espelho(str(self._evento().id))
        sincronizar_post_espelho(
            str(self._evento(titulo="Título novo", status="draft").id)
        )

        assert PostEspelho.objects.filter(wp_post_id=11).count() == 1
        espelho = PostEspelho.objects.get(wp_post_id=11)
        assert espelho.titulo == "Título novo"
        assert espelho.status == PostEspelhoStatus.RASCUNHO

    def test_remocao_vira_lixeira_e_nunca_apaga(self):
        # Apagar aqui derrubaria o PROTECT das FKs, que é o que preserva
        # comentário e IP sob a retenção de 6 meses do Marco Civil.
        sincronizar_post_espelho(str(self._evento().id))

        evento = self._evento(tipo="post_removido")
        sincronizar_post_espelho(str(evento.id))

        espelho = PostEspelho.objects.get(wp_post_id=11)
        assert espelho.status == PostEspelhoStatus.LIXEIRA
        assert PostEspelho.objects.count() == 1

    def test_wp_post_id_invalido_marca_erro_sem_derrubar(self):
        evento = self._evento(wp_post_id="não-é-número")

        sincronizar_post_espelho(str(evento.id))

        evento.refresh_from_db()
        assert evento.status == WebhookEventoStatus.ERRO
        assert PostEspelho.objects.count() == 0

    def test_evento_inexistente_nao_levanta(self):
        import uuid

        sincronizar_post_espelho(str(uuid.uuid4()))

        assert PostEspelho.objects.count() == 0


class TestMapeamentoDeStatus:
    """Story 3.3. Um post despublicado que continua aceitando comentário é o
    modo de falha silencioso que este mapeamento existe para tornar
    impossível."""

    @pytest.mark.parametrize(
        ("status_wp", "esperado"),
        [
            ("publish", PostEspelhoStatus.PUBLICADO),
            ("draft", PostEspelhoStatus.RASCUNHO),
            ("future", PostEspelhoStatus.AGENDADO),
            ("private", PostEspelhoStatus.PRIVADO),
            ("pending", PostEspelhoStatus.PENDENTE),
            ("trash", PostEspelhoStatus.LIXEIRA),
            ("auto-draft", PostEspelhoStatus.RASCUNHO),
            ("inherit", PostEspelhoStatus.RASCUNHO),
        ],
    )
    def test_os_sete_status_do_wordpress_tem_correspondencia(self, status_wp, esperado):
        assert traduzir_status(status_wp) == esperado

    @pytest.mark.parametrize(
        "desconhecido", ["", "publicado", "novo-status-do-wp-8", "PUBLISH"]
    )
    def test_status_desconhecido_nunca_vira_publicado(self, desconhecido):
        # AC2, fail-closed. É a regra que impede a falha silenciosa.
        assert traduzir_status(desconhecido) == PostEspelhoStatus.RASCUNHO

    def test_status_desconhecido_alerta(self):
        with patch("clama.blog.services.wordpress_webhook.sentry_sdk") as sentry:
            traduzir_status("status-inventado")

        sentry.capture_message.assert_called_once()
        assert sentry.capture_message.call_args.kwargs["level"] == "warning"

    def test_protegido_por_senha_nao_e_publico(self):
        # Proteção por senha é atributo, não status: no WordPress um post pode
        # ser `publish` E exigir senha. Quem não tem a senha não leu o post.
        assert (
            status_efetivo("publish", protegido_por_senha=True)
            == PostEspelhoStatus.PRIVADO
        )
        assert (
            status_efetivo("publish", protegido_por_senha=False)
            == PostEspelhoStatus.PUBLICADO
        )

    def test_senha_nao_promove_rascunho(self):
        # Rascunho protegido por senha continua rascunho — a proteção só
        # rebaixa, nunca sobe.
        assert (
            status_efetivo("draft", protegido_por_senha=True)
            == PostEspelhoStatus.RASCUNHO
        )

    @pytest.mark.django_db
    def test_o_booleano_form_encoded_e_interpretado(self):
        # Corpo form-encoded não tem tipo: o PHP manda "0" para falso, e
        # `bool("0")` em Python é True. Sem tradução, post desprotegido
        # viraria privado.
        registro, _ = WebhookEvento.objects.try_register(
            provider=WebhookProvider.WORDPRESS,
            external_event_id="evt-bool",
            event_type="post_publicado",
            payload={
                "wp_post_id": "21",
                "slug": "x",
                "titulo": "X",
                "status": "publish",
                "protegido_por_senha": "0",
            },
        )

        sincronizar_post_espelho(str(registro.id))

        assert (
            PostEspelho.objects.get(wp_post_id=21).status == PostEspelhoStatus.PUBLICADO
        )

    @pytest.mark.parametrize(
        "status_nao_publico",
        [
            PostEspelhoStatus.RASCUNHO,
            PostEspelhoStatus.PRIVADO,
            PostEspelhoStatus.AGENDADO,
            PostEspelhoStatus.LIXEIRA,
            PostEspelhoStatus.PENDENTE,
        ],
    )
    @pytest.mark.django_db
    def test_despublicado_nao_aceita_interacao(self, status_nao_publico):
        # AC4 da 3.3: o caso "post despublicado continuando a aceitar
        # comentário" é impossível por construção.
        from clama.blog.tests.factories import PostEspelhoFactory

        assert PostEspelhoFactory(status=status_nao_publico).aceita_interacao is False
