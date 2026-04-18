"""
Service para integração com a Files API da Anthropic.

Documentação: https://docs.anthropic.com/en/docs/build-with-claude/files

A Files API permite fazer upload de arquivos que podem ser referenciados
em mensagens usando document blocks com file_id.
"""

import logging
from typing import TYPE_CHECKING

import httpx
from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from clama.documents.models import DocumentoContexto

logger = logging.getLogger("clama.documents.anthropic_files")

# API constants
ANTHROPIC_FILES_API_URL = "https://api.anthropic.com/v1/files"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_FILES_BETA_HEADER = "files-api-2025-04-14"
REQUEST_TIMEOUT = 60.0  # Uploads podem demorar


class AnthropicFilesError(Exception):
    """Erro na comunicação com a Files API da Anthropic."""

    pass


class AnthropicFilesService:
    """
    Service para upload, listagem e deleção de arquivos na Anthropic.

    Usa a Files API (beta) para gerenciar arquivos que serão usados
    como contexto nas chamadas do Claude.

    Em modo mock (sem API key válida), simula as operações para
    permitir testes do fluxo completo.
    """

    # API keys que indicam modo mock
    MOCK_API_KEYS = {"", "test_api_key_for_local_development"}

    def __init__(self):
        """Inicializa o service com credenciais do settings."""
        api_key = settings.ANTHROPIC_API_KEY or ""
        self.mock_mode = api_key in self.MOCK_API_KEYS

        if self.mock_mode:
            logger.info(
                "AnthropicFilesService em modo mock",
                extra={"event": "anthropic_files_mock_mode", "reason": "no_valid_api_key"},
            )
            self._client = None
        else:
            self._api_key = api_key

    def _get_headers(self) -> dict:
        """Retorna headers padrão para a API."""
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "anthropic-beta": ANTHROPIC_FILES_BETA_HEADER,
        }

    def upload_file(self, documento: "DocumentoContexto") -> str:
        """
        Faz upload de um documento para a Files API da Anthropic.

        Args:
            documento: DocumentoContexto com arquivo para upload

        Returns:
            file_id retornado pela Anthropic

        Raises:
            AnthropicFilesError: Se o upload falhar
        """
        if self.mock_mode:
            # Gera file_id mock baseado no UUID do documento
            mock_file_id = f"file-mock-{str(documento.id)[:8]}"
            logger.info(
                "Upload mock realizado",
                extra={
                    "event": "anthropic_files_mock_upload",
                    "documento_id": str(documento.id),
                    "mock_file_id": mock_file_id,
                },
            )
            return mock_file_id

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                # Abre o arquivo para envio
                documento.arquivo.seek(0)
                file_content = documento.arquivo.read()

                response = client.post(
                    ANTHROPIC_FILES_API_URL,
                    headers=self._get_headers(),
                    files={
                        "file": (
                            documento.arquivo.name.split("/")[-1],
                            file_content,
                            documento.tipo_mime,
                        )
                    },
                )

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(
                        "Erro no upload para Anthropic",
                        extra={
                            "event": "anthropic_files_upload_error",
                            "documento_id": str(documento.id),
                            "status_code": response.status_code,
                            "error": error_detail[:500],
                        },
                    )
                    raise AnthropicFilesError(
                        f"Erro {response.status_code} ao fazer upload: {error_detail[:200]}"
                    )

                data = response.json()
                file_id = data.get("id")

                if not file_id:
                    raise AnthropicFilesError("Resposta da API não contém file_id")

                logger.info(
                    "Upload para Anthropic realizado",
                    extra={
                        "event": "anthropic_files_upload_success",
                        "documento_id": str(documento.id),
                        "file_id": file_id,
                        "tamanho_bytes": documento.tamanho_bytes,
                    },
                )

                return file_id

        except httpx.RequestError as e:
            logger.error(
                "Erro de conexão com Anthropic",
                extra={
                    "event": "anthropic_files_connection_error",
                    "documento_id": str(documento.id),
                    "error": str(e),
                },
            )
            raise AnthropicFilesError(f"Erro de conexão: {e}") from e

    def delete_file(self, file_id: str) -> bool:
        """
        Deleta um arquivo da Files API da Anthropic.

        Args:
            file_id: ID do arquivo na Anthropic

        Returns:
            True se deletado com sucesso

        Raises:
            AnthropicFilesError: Se a deleção falhar
        """
        if self.mock_mode:
            logger.info(
                "Delete mock realizado",
                extra={
                    "event": "anthropic_files_mock_delete",
                    "file_id": file_id,
                },
            )
            return True

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.delete(
                    f"{ANTHROPIC_FILES_API_URL}/{file_id}",
                    headers=self._get_headers(),
                )

                if response.status_code == 404:
                    # Arquivo já não existe, considera sucesso
                    logger.warning(
                        "Arquivo não encontrado na Anthropic (já deletado?)",
                        extra={
                            "event": "anthropic_files_not_found",
                            "file_id": file_id,
                        },
                    )
                    return True

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(
                        "Erro ao deletar arquivo na Anthropic",
                        extra={
                            "event": "anthropic_files_delete_error",
                            "file_id": file_id,
                            "status_code": response.status_code,
                            "error": error_detail[:500],
                        },
                    )
                    raise AnthropicFilesError(
                        f"Erro {response.status_code} ao deletar: {error_detail[:200]}"
                    )

                logger.info(
                    "Arquivo deletado na Anthropic",
                    extra={
                        "event": "anthropic_files_delete_success",
                        "file_id": file_id,
                    },
                )

                return True

        except httpx.RequestError as e:
            logger.error(
                "Erro de conexão ao deletar na Anthropic",
                extra={
                    "event": "anthropic_files_connection_error",
                    "file_id": file_id,
                    "error": str(e),
                },
            )
            raise AnthropicFilesError(f"Erro de conexão: {e}") from e

    def list_files(self) -> list[dict]:
        """
        Lista todos os arquivos na conta da Anthropic.

        Returns:
            Lista de dicts com informações dos arquivos

        Raises:
            AnthropicFilesError: Se a listagem falhar
        """
        if self.mock_mode:
            logger.info(
                "List mock realizado",
                extra={"event": "anthropic_files_mock_list"},
            )
            return []

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                response = client.get(
                    ANTHROPIC_FILES_API_URL,
                    headers=self._get_headers(),
                )

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(
                        "Erro ao listar arquivos na Anthropic",
                        extra={
                            "event": "anthropic_files_list_error",
                            "status_code": response.status_code,
                            "error": error_detail[:500],
                        },
                    )
                    raise AnthropicFilesError(
                        f"Erro {response.status_code} ao listar: {error_detail[:200]}"
                    )

                data = response.json()
                files = data.get("data", [])

                logger.info(
                    "Arquivos listados na Anthropic",
                    extra={
                        "event": "anthropic_files_list_success",
                        "count": len(files),
                    },
                )

                return files

        except httpx.RequestError as e:
            logger.error(
                "Erro de conexão ao listar na Anthropic",
                extra={
                    "event": "anthropic_files_connection_error",
                    "error": str(e),
                },
            )
            raise AnthropicFilesError(f"Erro de conexão: {e}") from e


def sincronizar_documento(documento: "DocumentoContexto") -> "DocumentoContexto":
    """
    Sincroniza um documento com a Files API da Anthropic.

    Faz upload do arquivo e atualiza o documento com o file_id.

    Args:
        documento: DocumentoContexto para sincronizar

    Returns:
        DocumentoContexto atualizado

    Raises:
        AnthropicFilesError: Se a sincronização falhar
    """
    service = AnthropicFilesService()
    file_id = service.upload_file(documento)

    documento.anthropic_file_id = file_id
    documento.data_sincronizacao = timezone.now()
    documento.save(update_fields=["anthropic_file_id", "data_sincronizacao", "updated_at"])

    return documento


def deletar_arquivo_anthropic(file_id: str) -> bool:
    """
    Deleta um arquivo da Files API da Anthropic.

    Args:
        file_id: ID do arquivo na Anthropic

    Returns:
        True se deletado com sucesso
    """
    service = AnthropicFilesService()
    return service.delete_file(file_id)
