# Retail POS Python — Instruções para agentes

Escopo: todo este repositório. Adaptado das instruções de engenharia do AgentDesk AI do usuário, para Python, Tkinter e SQLite. Mantenha este arquivo conciso, atualizado e verificável. README, relatório de outro agente e teste de abertura de janela não provam que uma funcionalidade funciona.

## 1. Missão e definição de sucesso

Este sistema apoia a operação real de um mercadinho: venda, estoque, compras, clientes/fiado, caixa, consumo interno, perdas, produção e validade.

Sucesso significa que o operador consegue concluir o fluxo completo e conferir seus efeitos em estoque, lotes, histórico e financeiro. Priorize correção dos dados e utilidade operacional antes de aparência ou quantidade de funcionalidades. Não declare o sistema pronto para produção, fiscalmente certificado ou integrado a equipamentos sem comprovação específica.

Interface e documentação do operador em português brasileiro, com nomes claros, moeda em reais e quantidades/unidades explícitas.

## 2. Descoberta antes de editar

- Leia README, requisitos, esquemas, testes e documentação pertinente.
- Confira `git status`, branch, commit e diferenças existentes; preserve trabalho do usuário.
- Confirme o comportamento atual no código e reproduza o problema em ambiente isolado.
- Não suponha que um commit citado existe no remoto, que uma pendência foi resolvida ou que um comando foi executado.
- Use a arquitetura existente; não migre para web, outro banco ou framework sem solicitação.

Mapa inicial, a reconfirmar no código:
- `app.py`, `gestao_ui.py`: interface Tkinter.
- `gestao.py`, `operacoes.py`: regras e operações.
- `producao.py`, `validade.py`: receitas, produção e lotes.
- `database.py`, `schema.sql`, `gestao_schema.sql`: persistência e migrações.
- `analises.py`, `relatorio_xlsx.py`: indicadores e exportações.
- `importar_*.py`, `backup.py`, `applock.py`: importações, recuperação e instância única.
- `balanca.py`, `impressora.py`: equipamentos.

## 3. Banco operacional e privacidade

- Trate `mercadinho.db`, configurações, backups, recibos e comprovantes como dados reais, mesmo que o README descreva um portfólio.
- Desenvolvimento e testes usam bancos temporários. Para avaliar migração de dados existentes, crie cópia consistente usando a API de backup SQLite com origem aberta em leitura.
- Redirecione `database.DB_PATH` antes de inicializar a aplicação ou chamar migrações; isole também caminhos de backup, configuração, logs e recibos quando houver escrita.
- Não execute seeds, testes, reparos ou migrações contra o banco da loja para validar mudanças.
- Não zere negativos em massa, invente custos/validade, reclassifique históricos ou apague auditoria. Saneamento exige dados conferidos e ação explícita do operador.
- Não publique dados de clientes, credenciais, bancos, backups ou screenshots reais. Use dados sintéticos nas evidências.
- Continue autonomamente as tarefas reversíveis autorizadas. Peça esclarecimento apenas para informação indispensável ou ação destrutiva/operacional sem autorização; não repita pedidos já respondidos.

## 4. Migrações e recuperação

- Toda alteração de esquema deve ter versão identificável e caminho testado de atualização desde a versão anterior.
- Verifique a condição real que dispara o backup. Adicionar colunas mantendo a mesma versão pode impedir backup pré-migração em instalações existentes.
- Backup deve ser consistente, ter integridade verificada e ocorrer antes da primeira modificação aplicável.
- Migrações devem ser repetíveis sem duplicação e preservar quantidades, custos, vendas e histórico, salvo transformação explicitamente prevista e validada.
- Teste `integrity_check`, `foreign_key_check`, contagens e invariantes relevantes antes/depois em cópia.
- Documente rollback de código separadamente de restauração de dados. Restaurar um backup antigo descarta lançamentos posteriores; nunca descreva isso como rollback sem consequências.
- Não alegue recuperação validada apenas porque foi possível criar um arquivo de backup.

## 5. Regras de negócio e transações

- Regras e permissões pertencem ao serviço; desabilitar botão não substitui autorização.
- Gravações compostas devem usar uma transação: cabeçalho, itens, estoque, lotes, custos, vínculos e auditoria. Falha intermediária reverte tudo.
- Quantidades e dinheiro precisam de validação finita, sinal, precisão e arredondamento consistente. Rejeite NaN/infinito. Não confunda custo desconhecido com custo econômico zero.
- Estoque negativo precisa de política explícita. Não use divisor artificial para custo médio nem libere baixas indevidas para mascarar divergências.
- Consumo operacional e pessoal não são vendas nem novas saídas de caixa. Produção transforma insumos em produto acabado; não registre os mesmos insumos novamente como consumo/perda.
- Preserve custo e descrição históricos. Não recalcule uma produção antiga usando a receita atual.
- Lote selecionado precisa pertencer ao produto, ter saldo e validade compatível com a operação. Consumo, produção e venda não usam vencidos; perdas podem baixá-los com rastreabilidade.
- Cancelamentos/estornos devem refletir em todos os indicadores. Histórico pode mostrar cancelados identificados, sem contá-los como operações efetivas.
- Não chame uma diferença parcial de produção/vendas de estoque final sem considerar saldo inicial e todas as movimentações.

## 6. Idempotência e estornos

- Use chave persistente por operação lógica, restrição no banco e transação para impedir repetição.
- A chave deve permanecer estável no reenvio da mesma tentativa. Audite também caminhos alternativos, como consumo em Ferramentas e perda pela tela de lotes.
- Defina o comportamento para mesma chave com conteúdo diferente; não retorne sucesso de uma operação antiga como se tivesse aplicado novos dados.
- Separe falha de gravação de falha de atualização após commit. A interface não deve induzir repetição de operação já salva.
- Estorno preserva original, motivo, autor e vínculos; não apaga histórico. Reverte lotes e custos conforme política documentada e impede estorno duplicado.
- Reversão de produção deve detectar dependências e uso posterior do produto acabado; não devolver insumos cegamente.

## 7. Interface e fluxos operacionais

- Buscar não é selecionar: não escolha automaticamente o primeiro insumo como identidade definitiva. Ao editar texto, invalide o ID até nova seleção explícita.
- Exiba nome, código, unidade, saldo utilizável e bloqueios relevantes; mantenha teclado e foco utilizáveis.
- Consumo: produto, quantidade, finalidade, responsável, centro de custo e custo conhecido/desconhecido.
- Perdas: produto, lote físico, quantidade, validade, motivo e responsável. Suporte perdas parciais e divisão entre lotes quando aplicável.
- Produção: receita, multiplicador, insumos necessários/disponíveis, rendimento previsto/real, validade e prévia de custo.
- Preserve entradas quando houver erro; atualize resumos e histórico após sucesso. Não ofereça confirmação de uma ação que o backend sempre rejeita.
- Exiba estados vazios, erro, sucesso e falta de permissão com orientação concreta.
- Não esconda falhas operacionais com `except Exception: pass`. Registre contexto e traceback sem dados sensíveis; apresente mensagem compreensível.
- Não inclua no roteiro do operador botões ou campos que ainda não existem.

## 8. Testes e evidências

Antes de alterar, registre os testes relevantes e falhas preexistentes. Após alterar, acrescente regressões comportamentais e execute verificações proporcionais. Não pule, enfraqueça ou simule sucesso de testes para encerrar a tarefa.

Comandos de referência, se presentes e após confirmar isolamento dos dados:

```bash
.venv/bin/python -m unittest test_gestao test_correcoes -v
.venv/bin/python test_producao_ui.py
.venv/bin/python test_interface.py
```

No Windows, use o executável correspondente da venv. Testes Tkinter exigem ambiente gráfico. Antes de usar `--loja`, confirme que a implementação trabalha exclusivamente em cópia e não exporta dados privados.

Cobertura prioritária:
- consumo/perdas em UN e KG, números inválidos, custo desconhecido e saldo insuficiente;
- lote vencido, de outro produto, falta de saldo e perda parcial;
- seleção de receita alterada, nomes semelhantes e busca vazia;
- produção com rendimento real diferente, insumo inativo e falha no segundo item;
- estoque negativo recomposto para negativo, zero e positivo;
- duplo envio e falha de interface depois do commit;
- cancelamento/estorno e reconciliação de relatórios;
- migração repetida de banco novo e cópia da versão anterior;
- regressões de venda, fiado, caixa, compras/importações e backup.

Abrir uma janela é smoke test. Para aceitar um fluxo, pesquise, selecione, preencha, confirme e confira os efeitos persistidos. Se capturar imagens, use a aplicação real com dados sintéticos. Equipamento simulado não comprova integração física.

## 9. Processo de entrega

1. Descreva o problema confirmado, o escopo e as incertezas.
2. Implemente uma etapa coerente em ordem de dependências e risco.
3. Teste sucesso, falhas e reconciliação; preserve trabalho existente.
4. Atualize documentação apenas com comportamento implementado e verificado.
5. Termine o escopo autorizado; não pare apenas para oferecer executar a próxima ação já solicitada.
6. Se uma decisão depender do negócio, preserve os dados, registre a pendência e conclua as tarefas independentes.

Refatore gradualmente os módulos extensos, sem reescrita ampla no mesmo pacote de correções. Não adicione dependências sem necessidade clara.

Na entrega informe: mudanças e motivo; arquivos; comandos realmente executados e resultado; testes não executados e impedimento; migrações/rollback; pendências e riscos concretos. Não declare trabalho integralmente concluído enquanto etapas solicitadas estiverem pendentes. Só afirme commit/push/publicação após confirmar a ação correspondente; siga a autorização do usuário para essas ações.
