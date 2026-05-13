"""
Mensagens pastorais consolidadas do Clama.

Todas as mensagens de erro, fallback e feedback ao usuário são centralizadas aqui
para garantir consistência de tom e facilitar revisão pastoral.

REGRAS DE TOM:
- Acolhedor, nunca culpabiliza a usuária
- Sem jargão técnico (evitar: error, exception, null, undefined, 500, timeout)
- Curto e direto, mas gentil
- Usar português brasileiro coloquial mas respeitoso

MANTER SINCRONIZADO:
- Frontend: src/lib/pastoral_messages.ts
"""

# =============================================================================
# ERROS DE REDE / INFRAESTRUTURA
# =============================================================================

# Usado quando há problemas de conexão ou servidor
MSG_NETWORK_ERROR = (
    "Tivemos um soluço na conexão. Tenta de novo em um minutinho?"
)

# Usado quando um erro inesperado acontece
MSG_UNKNOWN_ERROR = (
    "Algo não saiu como esperado. Estamos cuidando disso — tenta de novo mais tarde?"
)


# =============================================================================
# VALIDAÇÃO
# =============================================================================

# Erro genérico de validação
MSG_VALIDATION_GENERIC = (
    "Confira os campos preenchidos e tenta de novo."
)


# =============================================================================
# RATE LIMITING
# =============================================================================

# Usuária fez muitas requisições
MSG_RATE_LIMITED = (
    "Você fez vários pedidos seguidos — espera um instante e tenta de novo, com calma."
)


# =============================================================================
# PAGAMENTO
# =============================================================================

# Falha no processamento do pagamento
MSG_PAYMENT_FAILED = (
    "Não conseguimos processar seu pagamento agora. Tenta de novo ou usa outro método."
)

# Pedido já foi pago (tentativa duplicada)
MSG_PAYMENT_ALREADY_PAID = (
    "Esse pedido já foi processado. Vamos te encaminhar para a confirmação."
)


# =============================================================================
# GERAÇÃO DE ORAÇÃO
# =============================================================================

# Falha definitiva na geração
MSG_PRAYER_GENERATION_FAILED = (
    "Não conseguimos preparar sua oração agora. Vamos tentar de novo em breve."
)

# Oração reagendada para tentar novamente (fallback)
MSG_REAGENDADO = (
    "Sua oração precisou de mais um instante. "
    "Vamos enviar assim que estiver pronta — você não precisa fazer nada."
)

# Oração travada por falta de créditos na API — admin irá destravar em até 24h
MSG_ERRO_CREDITOS_24H = (
    "Recebemos seu pedido com carinho. Sua oração será preparada e enviada em até 24 horas. "
    "Se precisar falar com alguém antes, escreva pra contato@clama.me."
)


# =============================================================================
# EMAIL
# =============================================================================

# Falha no envio de email
MSG_EMAIL_FAILED = (
    "O envio do e-mail não foi possível agora. Vamos tentar de novo logo."
)


# =============================================================================
# WHATSAPP
# =============================================================================

# Falha no envio de WhatsApp
MSG_WHATSAPP_FAILED = (
    "O envio pelo WhatsApp não foi possível agora. Vamos tentar de novo logo."
)

# Hint para usuária ao escolher WhatsApp
MSG_WHATSAPP_HINT = (
    "Vamos te enviar pelo WhatsApp em até 2 minutos. Confira que seu número está correto."
)


# =============================================================================
# RECURSO NÃO ENCONTRADO
# =============================================================================

# Pedido ou recurso não encontrado
MSG_NOT_FOUND = (
    "Não encontramos o que você procura. Pode ter sido removido ou nunca existiu."
)


# =============================================================================
# AUTENTICAÇÃO / ADMIN
# =============================================================================

# Credenciais inválidas
MSG_INVALID_CREDENTIALS = (
    "E-mail ou senha não conferem. Tenta de novo."
)

# Não autenticado (precisa fazer login)
MSG_NOT_AUTHENTICATED = (
    "Você precisa entrar antes de acessar essa parte."
)

# Sem permissão (autenticado mas não é admin)
MSG_NO_PERMISSION = (
    "Esse espaço é só para admins do Clama."
)


# =============================================================================
# CONFIRMAÇÃO / FEEDBACK
# =============================================================================

# Mensagem de confirmação após pagamento (email)
MSG_CONFIRMACAO_EMAIL = (
    "Sua oração chegará na sua caixa de e-mail em até 2 minutos. "
    "Confira também a aba spam por garantia."
)

# Mensagem de confirmação após pagamento (WhatsApp)
MSG_CONFIRMACAO_WHATSAPP = (
    "Sua oração chegará no seu WhatsApp em até 2 minutos."
)

# Mensagem durante geração
MSG_GERANDO_ORACAO = (
    "Estamos preparando sua oração com cuidado."
)

# Mensagem quando enviada
MSG_ORACAO_ENVIADA_EMAIL = (
    "Sua oração já está aí! Confira seu e-mail."
)

MSG_ORACAO_ENVIADA_WHATSAPP = (
    "Sua oração já está aí! Confira seu WhatsApp."
)

# Mensagem de erro definitivo na confirmação
MSG_ERRO_DEFINITIVO = (
    "Tivemos um soluço — vamos reenviar logo. "
    "Se demorar, escreva pra contato@clama.me."
)


# =============================================================================
# VALIDAÇÃO DE TELEFONE
# =============================================================================

# Telefone inválido
MSG_TELEFONE_INVALIDO = (
    "Confira seu telefone com DDD — vamos enviar a oração por aqui."
)


# =============================================================================
# FREEMIUM (pedido gratuito)
# =============================================================================

# OTP inválido ou expirado (TTL passou ou código não bate)
MSG_FREEMIUM_OTP_INVALIDO = (
    "Código inválido ou expirado. Pede um novo código e tenta de novo."
)

# Rate limit do envio de OTP por telefone
MSG_FREEMIUM_OTP_RATE_LIMIT = (
    "Aguarde 1 minuto antes de pedir um novo código."
)

# Identificadores já usados (CPF/email/telefone na blacklist)
MSG_FREEMIUM_BLACKLIST_HIT = (
    "Você já recebeu sua oração gratuita. "
    "Sempre que quiser, pode fazer um novo pedido pela página principal."
)

# E-mail descartável detectado
MSG_FREEMIUM_EMAIL_DESCARTAVEL = (
    "Use um e-mail principal para receber sua oração — "
    "e-mails temporários não funcionam aqui."
)

# User já tem conta criada (gate user-existence) — orienta pra fazer login.
MSG_FREEMIUM_USER_JA_POSSUI_CONTA = (
    "Você já tem conta com a gente. Faça login pra fazer um novo pedido."
)

# Pedido pendente aguardando confirmação por email — orienta a verificar email.
MSG_FREEMIUM_PEDIDO_EM_ANDAMENTO = (
    "Você já tem um pedido aguardando confirmação. Confira seu e-mail "
    "para finalizar — se não achar, olha na aba de spam."
)


# =============================================================================
# CUSTOMER AUTH (login do user freemium pós-G1)
# =============================================================================

# Credenciais inválidas no /api/customer/auth/login/. Mensagem idêntica para
# email inexistente, senha errada e admin tentando logar (sem oracle de role).
MSG_CUSTOMER_LOGIN_FALHOU = (
    "E-mail ou senha não conferem. Tenta de novo."
)

# Senha trocada com sucesso no /change-password/.
MSG_CUSTOMER_PASSWORD_TROCADA = (
    "Senha atualizada com sucesso."
)

# 403 quando user logado tem force_change_password=True e tenta acessar
# endpoint protegido (exceto /me/ e /change-password/).
MSG_CUSTOMER_FORCE_CHANGE_PASSWORD = (
    "Antes de continuar, atualize sua senha."
)
