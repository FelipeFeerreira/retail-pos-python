"""Reformulação da interface do Retail POS.

Estrutura em módulos:
  tema.py         -> paleta e fontes (reaproveita a paleta do app atual)
  componentes.py  -> widgets reutilizáveis (período, busca de produto, tabela...)
  paginas.py      -> páginas por área (Início, Vendas, Produtos, ...)
  shell.py        -> janela principal, navegação e roteamento de páginas

As regras continuam nos serviços (gestao, operacoes, producao, analises). A
interface não contém SQL nem regra financeira.
"""
