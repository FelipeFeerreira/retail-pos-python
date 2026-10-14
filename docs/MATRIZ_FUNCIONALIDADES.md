# Matriz de funcionalidades — antiga (app.py) × nova (app_reformulado.py)

Legenda: **Impl** = implementada na nova interface · **Test** = coberta por teste
automatizado/jornada · **Pend** = ainda só na interface antiga · **Lim** = limitação.

## Vendas / PDV
| Função | Antiga | Nova | Test |
|---|---|---|---|
| Busca por nome/código + seleção explícita | sim | Impl | Test |
| Venda por unidade e por peso (KG) | sim | Impl (peso da balança ou digitado) | Test |
| Carrinho, remover, desconto por item e no total | sim | Impl | Test |
| Pagamento simples | sim | Impl | Test |
| Pagamento misto (2 formas) | sim | Impl | Test |
| Fiado com cliente e política | sim | Impl | Test |
| Cancelamento de venda | sim | Impl | Test (serviço) |
| Comprovante (impressão ESC/POS) | sim | Impl | Lim: sem impressora física |
| Abrir/fechar caixa | sim | Impl | Test |
| Balança Toledo 8217 | sim | Impl (mesmo módulo) | Lim: sem hardware |
| Visor do cliente | sim | Pend | — |
| Detalhe da venda com itens (histórico) | sim | Parcial (lista + reimpressão) | — |

## Clientes e fiado
| Cadastro/edição/pesquisa | sim | Impl | Test |
| Extrato por data | sim | Impl | Test (serviço) |
| Saldo e recebimento parcial | sim | Impl | Test |
| Política de crédito (limite/prazo/juros/multa) | sim | Impl | Test |
| Estorno de recebimento / comprovante | sim | Parcial (estorno no serviço; UI de recibo Pend) | — |

## Produtos e estoque
| Busca (nome/código/SKU), novo, editar | sim | Impl | Test |
| Custo conhecido/desconhecido | sim (v5) | Impl | Test |
| Ajuste por inventário (com motivo) | sim | Impl | Test |
| Lotes e validade (criar/listar) | sim | Impl | Test |
| Editar/excluir lote | sim | Pend | — |
| Importar planilha/NF-e | sim | Pend | — |

## Compras
| Receber compra (estoque + conta a pagar) | sim | Impl | Test |
| Compra com vários produtos / prévia | sim | Parcial (formulário direto) | — |

## Operacional
| Consumo interno (finalidade estável + motivo) | sim | Impl | Test |
| Perdas com seleção de lote físico | sim | Impl | Test |
| Produção com prévia e rendimento real | sim | Impl | Test |
| Receitas (cadastro/edição) | sim | Impl | Test (smoke) |
| Estorno de consumo/perda/produção | sim | Impl | Test |

## Financeiro
| Contas a pagar (nova/pagar/parcial) | sim | Impl | Test |
| Movimentos financeiros (lista) | sim | Impl | — |
| Contas a receber / Cartões / Contas e saldos | sim | Pend | — |
| Conciliação bancária / Orçamento | sim | Pend | — |

## Resultados / Análises
| Resultado gerencial + drill-down + caixa | sim | Impl | Test |
| Análises (tendência, dias, produtos, categorias) | sim | Pend | — |
| Exportar relatório XLSX | sim | Pend (reusa relatorio_xlsx) | — |

## Diagnóstico / Administração
| Diagnóstico (negativos, custo, lotes, validade, classificação) | parcial | Impl | Test |
| Classificação assistida de consumo | não | Impl | Test |
| Backup / restauração | sim | Impl | Test |
| Usuários / login / troca de usuário | sim | Impl | Test |
| Configurações (impressora, balança, tema, vouchers) | sim | Pend | — |
| Ferramentas (catálogo, duplicatas, inventário UI, reposição) | sim | Pend | — |

## Transversais
| Compatibilidade versão×esquema (bloqueia banco mais novo) | não | Impl | Test |
| Migrações versionadas com backup | sim | Impl | Test |
| Resolução 1366×768 (conteúdo cabe) | — | Impl | Test |
| Capturas de tela | — | Impossível no ambiente atual | Lim |

## Resumo
- **Implementadas e testadas na nova interface**: PDV (simples/misto/fiado/peso/cancelamento/caixa),
  clientes/fiado, produtos/estoque/lotes, compras, consumo/perdas/produção/receitas com estorno,
  contas a pagar, resultado gerencial com drill-down, diagnóstico assistido, administração (backup/usuários/logout),
  compatibilidade de esquema.
- **Pendentes de migração** (ainda na interface antiga): visor do cliente, edição/exclusão de lote,
  importações (planilha/NF-e), contas a receber/cartões/saldos, conciliação/orçamento, análises,
  exportação XLSX pela UI, configurações e ferramentas avançadas.
- **Limitações conhecidas**: captura de tela impossível (framebuffer virtual em branco);
  balança/impressora não validadas fisicamente.
