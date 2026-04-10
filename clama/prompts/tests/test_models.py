"""
Testes para os models do app prompts.
"""
import pytest

from clama.core.exceptions import PastoralAPIException
from clama.prompts.models import PromptTemplate
from clama.prompts.tests.factories import PromptTemplateFactory


@pytest.mark.django_db
class TestPromptTemplateModel:
    """Testes para o model PromptTemplate."""

    def test_seed_creates_one_active_template(self):
        """Seed deve criar exatamente um template ativo."""
        active_templates = PromptTemplate.objects.filter(ativo=True)
        assert active_templates.count() == 1
        assert active_templates.first().nome == "Clama Pastoral v1"

    def test_seed_template_has_correct_version(self):
        """Template do seed deve ter versão 1."""
        template = PromptTemplate.objects.get(nome="Clama Pastoral v1")
        assert template.versao == 1

    def test_seed_template_has_instrucoes(self):
        """Template do seed deve ter instruções por complexidade."""
        template = PromptTemplate.objects.get(nome="Clama Pastoral v1")
        assert "simples" in template.instrucoes_por_complexidade
        assert "com_versiculo" in template.instrucoes_por_complexidade
        assert "com_profecia_e_versiculos" in template.instrucoes_por_complexidade

    def test_template_has_uuid_pk(self):
        """PromptTemplate deve ter UUID como PK."""
        template = PromptTemplateFactory()
        assert template.id is not None
        assert len(str(template.id)) == 36

    def test_template_has_timestamps(self):
        """PromptTemplate deve ter created_at e updated_at."""
        template = PromptTemplateFactory()
        assert template.created_at is not None
        assert template.updated_at is not None

    def test_template_str_representation(self):
        """__str__ deve retornar nome e versão."""
        template = PromptTemplateFactory(nome="Test Prompt", versao=2)
        assert "Test Prompt" in str(template)
        assert "v2" in str(template)

    def test_active_template_str_shows_ativo(self):
        """__str__ de template ativo deve indicar status."""
        # Primeiro desativar o seed
        PromptTemplate.objects.filter(ativo=True).update(ativo=False)
        template = PromptTemplateFactory(nome="Active Test", versao=1, ativo=True)
        assert "(ativo)" in str(template)


@pytest.mark.django_db
class TestPromptTemplateSingleActive:
    """Testes para a constraint de único ativo."""

    def test_activating_template_deactivates_others(self):
        """Ativar um template deve desativar os outros."""
        # O seed já tem um template ativo
        original_active = PromptTemplate.objects.get(ativo=True)

        # Criar e ativar um novo template
        new_template = PromptTemplateFactory(ativo=True)

        # O original deve estar inativo agora
        original_active.refresh_from_db()
        assert original_active.ativo is False

        # O novo deve estar ativo
        new_template.refresh_from_db()
        assert new_template.ativo is True

    def test_only_one_active_at_a_time(self):
        """Deve haver no máximo um template ativo."""
        # Criar vários templates
        PromptTemplateFactory(ativo=True)
        PromptTemplateFactory(ativo=True)
        PromptTemplateFactory(ativo=True)

        # Apenas um deve estar ativo
        active_count = PromptTemplate.objects.filter(ativo=True).count()
        assert active_count == 1

    def test_can_deactivate_without_activating_other(self):
        """Pode desativar um template sem ativar outro."""
        # Desativar todos os templates
        PromptTemplate.objects.filter(ativo=True).update(ativo=False)

        # Criar um inativo
        template = PromptTemplateFactory(ativo=False)
        template.save()

        # Nenhum deve estar ativo
        assert PromptTemplate.objects.filter(ativo=True).count() == 0


@pytest.mark.django_db
class TestPromptTemplateGetActive:
    """Testes para o método get_active do manager."""

    def test_get_active_returns_active_template(self):
        """get_active deve retornar o template ativo."""
        active = PromptTemplate.objects.get_active()
        assert active.ativo is True
        assert active.nome == "Clama Pastoral v1"

    def test_get_active_raises_when_none_active(self):
        """get_active deve levantar exceção se nenhum ativo."""
        # Desativar todos
        PromptTemplate.objects.filter(ativo=True).update(ativo=False)

        with pytest.raises(PastoralAPIException) as exc_info:
            PromptTemplate.objects.get_active()

        assert exc_info.value.code == "no_active_prompt"
        assert exc_info.value.status_code == 500

    def test_get_active_returns_correct_after_activation(self):
        """get_active deve retornar o novo ativo após ativação."""
        new_template = PromptTemplateFactory(nome="New Active", ativo=True)

        active = PromptTemplate.objects.get_active()
        assert active.nome == "New Active"


@pytest.mark.django_db
class TestPromptTemplateInstrucoes:
    """Testes para instruções por complexidade."""

    def test_instrucoes_accepts_dict(self):
        """instrucoes_por_complexidade deve aceitar dict."""
        instrucoes = {
            "simples": "Instrução simples",
            "com_versiculo": "Instrução com versículo",
            "com_profecia_e_versiculos": "Instrução completa",
        }
        template = PromptTemplateFactory(instrucoes_por_complexidade=instrucoes)
        template.refresh_from_db()
        assert template.instrucoes_por_complexidade == instrucoes

    def test_can_access_specific_complexidade(self):
        """Deve poder acessar instrução de complexidade específica."""
        template = PromptTemplate.objects.get(nome="Clama Pastoral v1")
        assert "oração" in template.instrucoes_por_complexidade["simples"].lower()
