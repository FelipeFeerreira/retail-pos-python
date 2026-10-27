# pos-query — consultas read-only no PDV

## Uso
```bash
python3 pos_query.py --db /caminho/mercadinho.db resumo-hoje
python3 pos_query.py --db /caminho/mercadinho.db estoque-baixo --limite 10
python3 pos_query.py --db /caminho/mercadinho.db fiado --limite 10
python3 pos_query.py --db /caminho/mercadinho.db validade --dias 7
```
Sem `--db`, usa `$POS_DB` ou o `mercadinho.db` na mesma pasta.

## Garantias
- Abre o SQLite em `mode=ro` (somente leitura).
- Só stdlib. Sem `init_db()`, sem migração, sem escrita.
- Saída: `{"comando": ..., "dados": ...}`.

## MCP
```bash
pip install "mcp[cli]"
export POS_DB=/caminho/mercadinho.db
python3 mcp_server.py          # stdio
mcp dev mcp_server.py          # inspector
```
Ferramentas: `estoque_baixo`, `fiado_em_aberto`, `validade_proxima`, `resumo_do_dia`.

> `mcp_server.py` não foi executado ainda neste ambiente (pacote `mcp` ausente). É o próximo passo de verificação.

## Resultado da verificação (27/10/2026, banco real)
| Comando | Resultado |
|---|---|
| `resumo-hoje` | 20 vendas, R$ 274,71, R$ 22,97 a prazo |
| `fiado` | 24 clientes com saldo, soma R$ 1.291,41 |
| `estoque-baixo` | estoque negativo em produtos de produção (pão) |
| `validade` | 1 lote vencido com saldo |

## Limitações conhecidas
- `estoque-baixo` lista quantidade negativa como "falta": é sintoma de baixa sem entrada, não de contagem.
- `validade` inclui vencidos de propósito; a ordenação é por data.
- Sem paginação: use `--limite`.
