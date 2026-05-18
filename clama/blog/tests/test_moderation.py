import pytest

from clama.blog.moderation import (
    BLOG_PALAVRAS_SUSPEITAS,
    eh_comentario_suspeito,
)
from clama.blog.tests.factories import ComentarioFactory


class TestEhComentarioSuspeito:
    def test_empty_returns_false(self):
        assert eh_comentario_suspeito("") is False
        assert eh_comentario_suspeito(None) is False

    def test_clean_comment_returns_false(self):
        assert (
            eh_comentario_suspeito(
                "Belo texto pastoral, Pedro. Me ajudou muito hoje."
            )
            is False
        )

    def test_xingamento_obvio_returns_true(self):
        assert eh_comentario_suspeito("Que merda de texto") is True

    def test_case_insensitive(self):
        assert eh_comentario_suspeito("MERDA total") is True
        assert eh_comentario_suspeito("Merda total") is True

    def test_acentos_normalizados(self):
        # "satânico" deve bater com "satanico" no whitelist
        assert eh_comentario_suspeito("Texto satânico aqui") is True

    def test_word_boundary_evita_falso_positivo(self):
        # "cubuceta" não é match exato — não bate (word boundary)
        assert eh_comentario_suspeito("Vou comprar uma cubuceta nova") is False

    def test_palavra_dentro_de_paragrafo_grande(self):
        text = " ".join(["palavra"] * 100) + " caralho " + " ".join(["fim"] * 50)
        assert eh_comentario_suspeito(text) is True

    def test_spam_pattern_multi_palavra(self):
        assert eh_comentario_suspeito("Aproveite e compre agora!") is True
        assert eh_comentario_suspeito("Compre Agora seu curso") is True

    def test_spam_pattern_com_acento(self):
        assert eh_comentario_suspeito("Curso grátis hoje") is True

    def test_constante_e_frozenset(self):
        assert isinstance(BLOG_PALAVRAS_SUSPEITAS, frozenset)


@pytest.mark.django_db
class TestComentarioPreSaveSignal:
    def test_save_seta_is_suspeito_true_para_xingamento(self):
        c = ComentarioFactory(conteudo="que merda de texto")
        c.refresh_from_db()
        assert c.is_suspeito is True

    def test_save_mantem_false_para_limpo(self):
        c = ComentarioFactory(
            conteudo="Texto pastoral muito bom, me ajudou bastante."
        )
        c.refresh_from_db()
        assert c.is_suspeito is False

    def test_edit_para_conteudo_limpo_desflagia(self):
        c = ComentarioFactory(conteudo="que merda total")
        c.refresh_from_db()
        assert c.is_suspeito is True
        c.conteudo = "Texto limpo agora"
        c.save()
        c.refresh_from_db()
        assert c.is_suspeito is False

    def test_edit_para_conteudo_suspeito_flagia(self):
        c = ComentarioFactory(conteudo="Texto limpo")
        c.refresh_from_db()
        assert c.is_suspeito is False
        c.conteudo = "Compre agora seu produto"
        c.save()
        c.refresh_from_db()
        assert c.is_suspeito is True
