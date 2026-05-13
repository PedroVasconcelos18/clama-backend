# clama.blog — App Django do blog do Clama

> README completo virá com a Story 6.6 (NFR33). Este é um stub mínimo
> documentando processos operacionais críticos (LGPD).

## Atendimento LGPD — Exclusão de dados de customer

Quando um customer solicita exclusão dos próprios dados no blog:

1. **Validar identidade** — confirmar que o email do solicitante bate com
   um customer registrado no clama (`clama_backend.users.User`).

2. **Backup do estado** (opcional, mas recomendado pra auditoria):
   ```bash
   python manage.py dumpdata blog.Comentario blog.Reacao \
     --output backup-lgpd-<data>-<email>.json
   ```

3. **Preview do que será removido** (dry-run):
   ```bash
   python manage.py purgar_dados_blog_customer <email> --dry-run
   ```

4. **Executar a exclusão**:
   ```bash
   python manage.py purgar_dados_blog_customer <email> --yes
   ```

   O command:
   - Roda em `transaction.atomic` (ou tudo deleta ou nada)
   - Loga `purgar_dados_blog_customer_done` (audit trail) com `user_id`,
     `n_comentarios`, `n_reacoes`
   - **NÃO toca em**: User account, Pedido (clama core), `CustomerBanido`
     (auditoria de moderação preservada)

5. **Confirmação ao customer** — responder o email original em ≤30 dias
   (NFR11) confirmando a exclusão e os totais.

### Escopo

- ✅ `Comentario` do customer — deletados
- ✅ `Reacao` (likes) do customer — deletados
- 🚫 `User` (conta) — preservada (necessária pra pedidos do clama core)
- 🚫 `Pedido` (clama core) — preservado (escopo separado)
- 🚫 `CustomerBanido` — preservado (auditoria de moderação; admin pode
  revogar manualmente se apropriado)

Se o customer também solicitar exclusão completa da conta (não apenas
do blog), seguir o procedimento LGPD do clama core (escopo separado).
