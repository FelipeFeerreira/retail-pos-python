"""
categorias.py

Acaba com as categorias vazias do cadastro e mantém a lista de categorias
padronizada — o que é pré-requisito pra margem por categoria funcionar na
precificação (se o produto não tem categoria, não tem como saber qual
porcentagem aplicar em cima do custo dele).

Como funciona: cada produto sem categoria (ou com categoria fora do padrão)
passa por uma lista de regras por palavra-chave, na ordem. A primeira regra
que casa define a categoria. O que não casar com nenhuma regra cai em
"Mercearia Geral" e é marcado como "revisar" no relatório — nunca fica vazio,
mas também não finge que o palpite foi certeiro.

Nada é gravado sem antes fazer uma cópia do banco em backups/.

Uso pela interface: Arquivo -> Revisar categorias dos produtos.
Uso direto:
    python categorias.py            (só mostra o que faria, não grava)
    python categorias.py --aplicar  (grava de verdade)
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime

import database as db

# Lista oficial de categorias do sistema. É essa lista que a planilha de
# precificação usa pra montar a tabela de margens.
CATEGORIAS = [
    'Mercearia Geral',
    'Panificação',
    'Doces e Biscoitos',
    'Salgadinhos e Snacks',
    'Bebidas',
    'Bebidas Alcoólicas',
    'Balança',
    'Frios e Congelados',
    'Prontos do Dia',
    'Limpeza de Casa',
    'Higiene Pessoal',
    'Bazar e Utilidades',
]

CATEGORIA_FALLBACK = 'Mercearia Geral'

# Regras na ordem de prioridade: (categoria, expressão regular no nome).
# \b marca começo/fim de palavra — importante pra token curto não casar no
# meio de outra palavra (sem isso "ELGIN SONIC" viraria bebida alcoólica por
# causa do "GIN").
REGRAS = [
    ('Bebidas Alcoólicas', r'CERVEJ|\bSKOL\b|\bBRAHMA\b|AMSTEL|HEINEKEN|BUDWEISER|ITAIPAVA|'
                           r'CRYSTAL BEER|\bBEER\b|\bLAGER\b|PILSEN|BOHEMIA|SERRAMALTE|SPATEN|'
                           r'EISENBAHN|DEVASSA|NOVA SCHIN|BAVARIA|KAISER|\bPETRA\b|STELLA|CORONA|'
                           r'\bBECKS\b|\bIPA\b|VINHO|ESPUMANTE|SIDRA|\bVODKA\b|WHISK|CACHACA|'
                           r'CACHAÇA|\bPITU\b|VELHO BARREIRO|CATUABA|CONHAQUE|\bLICOR\b|\bGIN\b|'
                           r'\bRUM\b|SMIRNOFF|ASKOV|ORLOFF|BALLANTINE|RED LABEL|JACK DANIEL|'
                           r'NATU NOBILIS|\bDREHER\b'),

    ('Higiene Pessoal', r'SHAMPO|XAMPU|CONDICIONADOR|CREME P(ARA|RA) PENTEAR|SABONETE|DESODORANTE|'
                        r'REXONA|NIVEA|DOVE|\bSEDA\b|CLEAR MEN|LISTERINE|ENXAGUANTE|CREME DENTAL|'
                        r'ESCOVA DENTAL|PASTA DE DENTE|COLGATE|SORRISO|ORAL ?B|ABSORVENTE|'
                        r'SEMPRELIVRE|INTIMUS|PAPEL HIGIENICO|PAPEL HIGIÊNICO|FRALDA|COTTON|'
                        r'HASTES FLEXIVEIS|COTONETE|\bGEL FIXADOR\b|SOFT GEL|KOLENE|POMPOM|'
                        r'BARBEAR|GILLETE|GILLETTE|PROTETOR SOLAR|HIDRATANTE|TALCO|ACETONA|'
                        r'\bLENCO UMEDECIDO\b|PERFUM'),

    ('Limpeza de Casa', r'DETERGENTE|AMACIANTE|SABAO|SABÃO|AGUA SANITARIA|ÁGUA SANITARIA|CANDIDA|'
                        r'CLORO|DESINFETANTE|MULTIUSO|\bVEJA\b|\bYPE\b|\bYPÊ\b|MINUANO|MINUANI|'
                        r'\bOMO\b|\bTIXAN\b|\bBRILHANTE\b|\bASSIM\b|LIMPADOR|LUSTRA|\bAJAX\b|'
                        r'\bPINHO\b|\bVANISH\b|ESPONJA|\bBOMBRIL\b|\bASSOLAN\b|SACO DE LIXO|'
                        r'PAPEL TOALHA|SOCIAL CLEAN|\bRODO\b|VASSOURA|\bPANO DE CHAO\b|'
                        r'\bALVEJANTE\b|TIRA MANCHA|INSETICIDA|\bSBP\b|\bRAID\b|NAFTALINA'),

    ('Bazar e Utilidades', r'\bPILHA|\bPILHAS\b|ISQUEIRO|\bVELA\b|\bVELAS\b|MOROABA|PRENDEDOR|'
                           r'HOT WHEELS|BRINQUEDO|\bBONECA\b|CARRINHO DE BRINQUEDO|\bLAMPADA\b|'
                           r'\bLÂMPADA\b|EXTENSAO|\bCOPO\b|\bPRATO DESCARTAVEL\b|GUARDANAPO|'
                           r'\bCARVAO\b|\bCARVÃO\b|\bFOSFORO\b|\bFÓSFORO\b|CANETA|\bCADERNO\b|'
                           r'\bPAPEL ALUMINIO\b|FILME PLASTICO|\bLINHA\b|\bAGULHA\b'),

    # "Prontos do Dia" = o que o mercadinho monta/revende pronto pra consumo
    # (salgado, espeto, bolo de pote, mousse, açaí). Vem antes de tudo porque
    # é a categoria de maior margem e não pode se perder em Panificação.
    ('Prontos do Dia', r'\bEMPADA\b|COXINHA|\bESPETO\b|SALGADO VARIADO|\bSALGADO\b|\bPASTEL\b|'
                       r'\bKIBE\b|\bQUIBE\b|ESFIHA|ESFIRRA|BOLO DE POTE|\bMOUSSE\b|'
                       r'\bAÇAI\b|\bACAI\b|MARMITA|\bCOMBO\b|\bSANDUICHE\b|\bMISTO QUENTE\b|'
                       r'\bTORTA DOCE\b|\bTORTA SALGADA\b|GARRAFINHA'),

    ('Panificação', r'\bPANCO\b|\bPULLMAN\b|\bBIMBO\b|\bSEVEN BOYS\b|MARQUESPAN|\bPAO\b|\bPÃO\b|'
                    r'\bBISNAGA|BISNAGUIT|BISNAGUINH|\bROSQUINHA\b|\bSOVADO\b|SOVADINHO|'
                    r'\bBOLO\b|\bBOLINHO\b|PINGUINOS|BEBEZINHO|PANQUINHO|'
                    r'\bSEQUILHO|\bTORRADA\b|\bCROISSANT\b|EGG SPONGE|'
                    r'CREAM SODA|\bPAO DE MEL\b'),

    # Salgadinho vem antes de frios: "CROCANTISSIMO PEITO DE PERU" é
    # salgadinho de pacote, não peito de peru fatiado.
    ('Salgadinhos e Snacks', r'\bRUFFLES\b|\bDORITOS\b|\bCHEETOS\b|\bFANDANGOS\b|\bLAYS\b|'
                             r'\bTORCIDA\b|\bPINGO DOURADO\b|\bBACONZITOS\b|\bTAKIS\b|\bTAKES\b|'
                             r'POINTCHIPS|\bCHIPS\b|\bPIPOCA\b|\bAMENDOIM\b|\bCASTANHA\b|'
                             r'\bSALGADINHO|CROCANTISSIMO|\bPOLVILHO\b|'
                             r'\bPETISCO\b|\bBATATA PALHA\b|\bNACHO|BACON BITS'),

    ('Frios e Congelados', r'\bSADIA\b|\bPERDIGAO\b|\bPERDIGÃO\b|\bSEARA\b|HAMBURGUER|HAMBÚRGUER|'
                           r'\bNUGGET|LINGUICA|LINGUIÇA|SALSICHA|\bMORTADELA\b|\bPRESUNTO\b|'
                           r'\bMUSSARELA\b|\bREQUEIJAO\b|\bMANTEIGA\b|\bMARGARINA\b|\bIOGURTE\b|'
                           r'\bBACON\b|\bPEITO DE PERU\b|\bFRANGO\b|\bCARNE\b|\bPICANHA\b|'
                           r'\bCOSTELA\b|\bEMPANADO\b|\bCONGELAD|\bPOLPA DE FRUTA\b'),

    ('Doces e Biscoitos', r'\bCHOCOLATE\b|\bBOMBOM\b|\bBALA\b|\bBALAS\b|\bPIRULITO\b|\bCHICLETE\b|'
                          r'\bHALLS\b|\bMENTOS\b|\bTRIDENT\b|\bFINI\b|\bDOCILE\b|\bSNICKERS\b|'
                          r'\bBON O BON\b|\bKITKAT\b|\bKIT KAT\b|\bLACTA\b|\bNESTLE\b|\bGAROTO\b|'
                          r'\bBIS\b|\bTRENTO\b|\bBISCOITO\b|\bMAIZENA\b|\bWAFER\b|\bRECHEADO\b|'
                          r'\bCREMOSINHO\b|\bSORVETE\b|\bPICOLE\b|\bGELADINHO\b|\bPACOCA\b|'
                          r'\bPAÇOCA\b|\bPE DE MOCA\b|\bPE DE MOLEQUE\b|\bDOCE DE LEITE\b|'
                          r'\bGOIABADA\b|\bAMENDOIM DOCE\b|\bTABLETE\b'),

    ('Bebidas', r'\bCOCA\b|COCA COLA|\bFANTA\b|\bSPRITE\b|\bKUAT\b|\bGUARANA\b|\bGUARANÁ\b|'
                r'\bPEPSI\b|\bSUKITA\b|TUBAINA|TUIUBAINA|\bDOLLY\b|\bSCHWEPPES\b|\bREFRIGERANTE\b|'
                r'DEL VALLE|\bKAPO\b|\bSUCO\b|\bNECTAR\b|\bNÉCTAR\b|MAGUARY|\bDAFRUTA\b|'
                r'\bTANG\b|\bCLIGHT\b|\bBALY\b|\bMONSTER\b|\bTNT\b|RED BULL|\bENERG\b|'
                r'ENERGETICO|ISOTONICO|POWER ?ADE|GATORADE|\bAGUA\b|\bÁGUA\b|\bAQUA\b|'
                r'\bMINERAL\b|\bMATE\b|'
                r'SEGREDO DE UVA|NOVA ALIANÇA|^IT\b'),

    ('Balança', r'\bA GRANEL\b|\bGRANEL\b'),

    # Regra final antes do fallback: itens clássicos de prateleira seca.
    # Serve pra esses produtos não serem marcados como "revisar" sem motivo.
    ('Mercearia Geral', r'\bARROZ\b|\bFEIJAO\b|\bFEIJÃO\b|ACUCAR|AÇUCAR|AÇÚCAR|\bSAL\b|\bOLEO\b|'
                        r'\bÓLEO\b|\bAZEITE\b|FARINHA|\bMACARRAO\b|\bMACARRÃO\b|\bESPAGUETE\b|'
                        r'\bPARAFUSO\b|\bTALHARIM\b|\bLASANHA\b|DONA BENTA|\bMOLHO\b|\bEXTRATO\b|'
                        r'\bSARDINHA|\bATUM\b|\bCONSERVA\b|\bMILHO\b|\bERVILHA\b|\bSELETA\b|'
                        r'\bLEITE\b|\bNINHO\b|ITALAC|PIRACANJUBA|\bCREME DE LEITE\b|'
                        r'\bACHOCOLATADO\b|\bTODDY\b|\bNESCAU\b|\bFERMENTO\b|\bAMIDO\b|'
                        r'\bCAFE\b|\bCAFÉ\b|\bCHA\b|\bCHÁ\b|\bFILTRO DE PAPEL\b|'
                        r'\bTEMPERO\b|\bVINAGRE\b|\bMAIONESE\b|\bKETCHUP\b|\bMOSTARDA\b|'
                        r'\bSHOYU\b|\bAVEIA\b|\bGRANOLA\b|\bTAPIOCA\b|\bCUSCUZ\b|\bFUBA\b|'
                        r'\bPOLENTA\b|\bCANJICA\b|\bGELATINA\b|\bPUDIM\b|\bSOPA\b|\bCALDO\b'),
]


def _compiladas():
    return [(cat, re.compile(padrao)) for cat, padrao in REGRAS]


def sugerir_categoria(nome, unidade=None, categoria_atual=None):
    """Devolve (categoria_sugerida, veio_de_regra).

    veio_de_regra=False significa que nenhuma palavra-chave casou e a
    categoria caiu no fallback — ou seja, vale o dono dar uma olhada.
    """
    texto = (nome or '').upper()
    # Produto vendido por quilo num mercadinho de bairro é, quase sempre,
    # item de balança (fruta, verdura, granel) — salvo carne/frios.
    for categoria, regex in _compiladas():
        if regex.search(texto):
            return categoria, True
    if unidade == 'KG':
        return 'Balança', True
    return CATEGORIA_FALLBACK, False


def _precisa_arrumar(categoria):
    return not categoria or not str(categoria).strip() or str(categoria).strip() not in CATEGORIAS


def analisar():
    """Monta a lista de mudanças propostas, sem gravar nada.

    Devolve {'mudancas': [...], 'revisar': [...], 'resumo': {categoria: n}}
    """
    conn = db.get_conn()
    try:
        produtos = [dict(r) for r in conn.execute(
            'SELECT id, nome, unidade, categoria, preco_venda FROM produtos WHERE ativo = 1 ORDER BY nome')]
    finally:
        conn.close()

    mudancas, revisar = [], []
    for p in produtos:
        atual = (p['categoria'] or '').strip()
        if not _precisa_arrumar(atual):
            continue
        sugerida, por_regra = sugerir_categoria(p['nome'], p['unidade'], atual)
        if sugerida == atual:
            continue
        item = {
            'id': p['id'], 'nome': p['nome'], 'unidade': p['unidade'],
            'de': atual or '(vazia)', 'para': sugerida, 'confiante': por_regra,
        }
        mudancas.append(item)
        if not por_regra:
            revisar.append(item)

    resumo = {}
    for m in mudancas:
        resumo[m['para']] = resumo.get(m['para'], 0) + 1
    return {'mudancas': mudancas, 'revisar': revisar, 'resumo': resumo}


def analisar_divergencias():
    """Produtos que JÁ têm uma categoria válida, mas cujo nome indica outra
    com boa confiança — tipo cerveja cadastrada em "Bebidas" (o certo seria
    "Bebidas Alcoólicas", que tem margem diferente) ou pilha em "Mercearia".

    É só um relatório: o dono decide se quer aplicar ou não, porque aqui a
    categoria atual foi escolhida por ele e não está vazia.
    """
    conn = db.get_conn()
    try:
        produtos = [dict(r) for r in conn.execute(
            'SELECT id, nome, unidade, categoria FROM produtos WHERE ativo = 1 ORDER BY nome')]
    finally:
        conn.close()

    divergencias = []
    for p in produtos:
        atual = (p['categoria'] or '').strip()
        if _precisa_arrumar(atual):
            continue  # esse caso é tratado por analisar()
        sugerida, por_regra = sugerir_categoria(p['nome'], p['unidade'], atual)
        if por_regra and sugerida != atual:
            divergencias.append({
                'id': p['id'], 'nome': p['nome'], 'unidade': p['unidade'],
                'de': atual, 'para': sugerida, 'confiante': True,
            })
    return divergencias


def _backup_antes_de_gravar():
    pasta = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), 'backups')
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f'mercadinho_antes_categorias_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    shutil.copy2(db.DB_PATH, destino)
    return destino


def aplicar(mudancas=None):
    """Grava as mudanças no banco, depois de fazer uma cópia de segurança.
    Devolve (quantidade_aplicada, caminho_do_backup)."""
    import gestao as _gestao
    _gestao.permitir('estoque')
    if mudancas is None:
        mudancas = analisar()['mudancas']
    if not mudancas:
        return 0, None
    backup = _backup_antes_de_gravar()
    conn = db.get_conn()
    try:
        for m in mudancas:
            conn.execute('UPDATE produtos SET categoria = ? WHERE id = ?', (m['para'], m['id']))
        conn.commit()
    finally:
        conn.close()
    return len(mudancas), backup


def contagem_por_categoria():
    """Quantos produtos ativos em cada categoria, incluindo as vazias
    (pra interface poder mostrar que zerou)."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(categoria), ''), '(vazia)') cat, COUNT(*) n
               FROM produtos WHERE ativo = 1 GROUP BY cat ORDER BY n DESC""").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == '__main__':
    db.init_db()
    resultado = analisar()
    if not resultado['mudancas']:
        print('Nenhum produto com categoria vazia ou fora do padrão. Cadastro está limpo.')
        sys.exit(0)

    print(f"{len(resultado['mudancas'])} produto(s) para arrumar:\n")
    for m in resultado['mudancas']:
        marca = '' if m['confiante'] else '   <-- REVISAR (palpite pelo fallback)'
        print(f"  [{m['de']}] -> [{m['para']}]  {m['nome']}{marca}")

    print('\nResumo por categoria de destino:')
    for cat, n in sorted(resultado['resumo'].items(), key=lambda x: -x[1]):
        print(f'  {cat}: {n}')

    if resultado['revisar']:
        print(f"\n{len(resultado['revisar'])} produto(s) caíram no fallback e merecem sua conferência.")

    if '--aplicar' in sys.argv:
        n, backup = aplicar(resultado['mudancas'])
        print(f'\n{n} categoria(s) gravada(s). Cópia de segurança do banco em: {backup}')
    else:
        print('\n(Nada foi gravado. Rode com --aplicar para gravar de verdade.)')
