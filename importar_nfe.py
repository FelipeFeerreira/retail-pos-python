"""
importar_nfe.py

Importa notas fiscais de fornecedor (NF-e) para o sistema.

- Formato principal: XML da NF-e (padrao nacional). Aceita:
    * um arquivo .xml
    * varios .xml de uma vez
    * um .zip contendo .xml
    * uma pasta com .xml
    * o PDF do DANFE, tentando extrair o XML embutido (pypdf)

O que faz (duas etapas, igual a importacao de planilha):
    pre_visualizar(caminho) -> le e monta o plano SEM gravar nada
    aplicar(caminho, plano, opcoes) -> grava de verdade (com backup antes)

Ao aplicar, para cada nota:
    * casa o produto pelo codigo de barras (cEAN) e, se nao achar, pelo nome
    * cadastra os produtos que ainda nao existem
    * da entrada no estoque com custo medio (via gestao.receber_compra)
    * registra o historico da compra (compras_estoque/itens_compra)
    * lanca a conta a pagar do fornecedor (Financeiro)

Uso pela interface: Arquivo -> Importar nota fiscal (NF-e).
"""
from __future__ import annotations

import io
import os
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import database as db
import operacoes as op

try:
    import pypdf
except ImportError:
    pypdf = None

VALOR_SEM_GTIN = ('SEM GTIN', 'SEMGTIN', '0000000000000', '00000000000000')


# ---------------------------------------------------------------------------
# Leitura do XML
# ---------------------------------------------------------------------------
def _strip(tag):
    return tag.split('}')[-1]


def _filho(el, tag):
    for c in el:
        if _strip(c.tag) == tag:
            return c
    return None


def _filhos(el, tag):
    return [c for c in el if _strip(c.tag) == tag]


def _texto(el, tag):
    f = _filho(el, tag) if el is not None else None
    return (f.text or '').strip() if f is not None and f.text else ''


def _num(valor):
    try:
        return float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return 0.0


def _parse_xml_bytes(dados):
    """Le os bytes de uma NF-e e devolve um dicionario com a nota."""
    raiz = ET.fromstring(dados)
    inf = None
    for el in raiz.iter():
        if _strip(el.tag) == 'infNFe':
            inf = el
            break
    if inf is None:
        raise ValueError('O XML nao parece ser uma NF-e (nao encontrei a tag infNFe).')

    chave = (inf.get('Id') or '').replace('NFe', '').strip()
    ide = _filho(inf, 'ide')
    emit = _filho(inf, 'emit')
    total = _filho(inf, 'total')
    icms = _filho(total, 'ICMSTot') if total is not None else None

    nota = {
        'chave': chave,
        'numero': _texto(ide, 'nNF'),
        'serie': _texto(ide, 'serie'),
        'data': _texto(ide, 'dhEmi') or _texto(ide, 'dEmi'),
        'fornecedor': _texto(emit, 'xNome'),
        'cnpj': _texto(emit, 'CNPJ') or _texto(emit, 'CPF'),
        'valor_total': _num(_texto(icms, 'vNF')),
        'itens': [],
        'duplicatas': [],
    }

    for det in _filhos(inf, 'det'):
        prod = _filho(det, 'prod')
        if prod is None:
            continue
        ean = _texto(prod, 'cEAN').strip()
        if ean.upper() in VALOR_SEM_GTIN:
            ean = ''
        unidade = (_texto(prod, 'uCom') or 'UN').upper()
        custo = _num(_texto(prod, 'vUnCom')) or _num(_texto(prod, 'vUnTrib'))
        nota['itens'].append({
            'codigo': _texto(prod, 'cProd'),
            'ean': ean,
            'nome': _texto(prod, 'xProd'),
            'ncm': _texto(prod, 'NCM'),
            'cfop': _texto(prod, 'CFOP'),
            'unidade': 'KG' if 'KG' in unidade else 'UN',
            'quantidade': _num(_texto(prod, 'qCom')),
            'custo_unitario': custo,
            'total': _num(_texto(prod, 'vProd')),
        })

    for dup in inf.iter():
        if _strip(dup.tag) == 'dup':
            nota['duplicatas'].append({
                'numero': _texto(dup, 'nDup'),
                'vencimento': _texto(dup, 'dVenc'),
                'valor': _num(_texto(dup, 'vDup')),
            })

    return nota


def _extrair_xml_de_pdf(caminho):
    """Tenta obter o XML embutido no PDF do DANFE (anexo ou stream)."""
    if pypdf is None:
        return None
    try:
        leitor = pypdf.PdfReader(caminho)
        # 1) anexos /EmbeddedFiles
        try:
            anexos = leitor.attachments
            for nome in anexos or {}:
                conteudo = leitor.attachments[nome]
                if isinstance(conteudo, (list, tuple)):
                    conteudo = conteudo[-1]
                if isinstance(conteudo, str):
                    conteudo = conteudo.encode('latin-1', 'ignore')
                if b'<nfeProc' in conteudo or b'<NFe' in conteudo:
                    return conteudo
        except Exception:
            pass
        # 2) varredura dos streams
        for pagina in leitor.pages:
            try:
                for conteudo in pagina.get_contents():
                    dados = conteudo.get_data()
                    if b'<nfeProc' in dados or b'<NFe' in dados:
                        ini = dados.find(b'<nfeProc')
                        if ini < 0:
                            ini = dados.find(b'<NFe')
                        fim = dados.rfind(b'</nfeProc>')
                        if fim < 0:
                            fim = dados.rfind(b'</NFe>')
                        if fim > ini:
                            return dados[ini:fim + 8]
            except Exception:
                continue
    except Exception:
        return None
    return None


def _ler_arquivo(caminho):
    """Le um arquivo e devolve a lista de notas (aceita xml, pdf, zip)."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext == '.xml':
        with open(caminho, 'rb') as f:
            return [_parse_xml_bytes(f.read())]
    if ext == '.zip':
        notas = []
        with zipfile.ZipFile(caminho) as z:
            for nome in z.namelist():
                if nome.lower().endswith('.xml'):
                    notas.append(_parse_xml_bytes(z.read(nome)))
        return notas
    if ext == '.pdf':
        dados = _extrair_xml_de_pdf(caminho)
        if dados is None:
            raise ValueError('Nao consegui achar o XML dentro desse PDF/DANFE. '
                             'Peca o XML da nota ao fornecedor (é o formato com os dados).')
        return [_parse_xml_bytes(dados)]
    raise ValueError(f'Formato nao suportado: {ext}. Use XML, ZIP ou o PDF do DANFE.')


def _coletar_caminhos(caminho):
    """Normaliza a entrada (arquivo, lista, pasta) para uma lista de arquivos."""
    if isinstance(caminho, (list, tuple)):
        arquivos = []
        for c in caminho:
            arquivos.extend(_coletar_caminhos(c))
        return arquivos
    if os.path.isdir(caminho):
        arquivos = []
        for nome in sorted(os.listdir(caminho)):
            arquivos.extend(_coletar_caminhos(os.path.join(caminho, nome)))
        return arquivos
    ext = os.path.splitext(caminho)[1].lower()
    if ext in ('.xml', '.pdf', '.zip'):
        return [caminho]
    return []


# ---------------------------------------------------------------------------
# Plano (pre-visualizacao)
# ---------------------------------------------------------------------------
def _buscar_produto(ean, nome):
    if ean:
        p = op.buscar_por_codigo(ean)
        if p:
            return p
    conn = db.get_conn()
    try:
        row = conn.execute(
            'SELECT * FROM produtos WHERE UPPER(TRIM(nome)) = ? AND ativo = 1',
            (nome.strip().upper(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _margem_categoria(categoria):
    try:
        from precificacao import margem_da_categoria
        return margem_da_categoria(categoria)
    except Exception:
        return 50.0


def _nota_ja_importada(conn, nota):
    """True se a compra dessa nota já foi registrada (pela chave da NF-e ou
    pelo par fornecedor+documento). Evita importar a mesma nota duas vezes."""
    chave = 'nfe_' + (nota['chave'] or nota['numero'])
    if conn.execute('SELECT 1 FROM compras_estoque WHERE chave=?', (chave,)).fetchone():
        return True
    return bool(conn.execute('SELECT 1 FROM compras_estoque WHERE fornecedor=? AND documento=?',
                             (nota['fornecedor'], nota['numero'])).fetchone())


def pre_visualizar(caminho):
    """Le as notas e monta o plano. Nao grava nada no banco.

    Regra de ouro: NÃO inventa dados. Se a nota não traz o vencimento/condição
    de pagamento, o plano sinaliza que é preciso confirmar; o mesmo vale para
    a validade de produtos perecíveis, que a NF-e normalmente não informa."""
    arquivos = _coletar_caminhos(caminho)
    if not arquivos:
        raise ValueError('Nenhum arquivo XML/PDF/ZIP valido foi selecionado.')

    notas, itens = [], []
    for arq in arquivos:
        for nota in _ler_arquivo(arq):
            nota['arquivo'] = arq
            if not nota['fornecedor']:
                nota['fornecedor'] = 'Fornecedor (nao informado)'
            if not nota['numero']:
                nota['numero'] = 'S/N'
            # Vencimento/condição: usa a duplicata real da nota. Se não houver,
            # deixa em branco (não presume 30 dias nem "A prazo").
            if nota['duplicatas']:
                vencs = sorted(d['vencimento'] for d in nota['duplicatas'] if d['vencimento'])
                nota['vencimento'] = vencs[-1] if vencs else None
                nota['forma'] = 'A prazo'
            else:
                nota['vencimento'] = None
                nota['forma'] = None
            nota['avisos'] = []
            if nota['vencimento'] is None:
                nota['avisos'].append('sem vencimento na nota — confirme a condição de pagamento')
            conn = db.get_conn()
            try:
                nota['duplicada'] = _nota_ja_importada(conn, nota)
            finally:
                conn.close()
            if nota['duplicada']:
                nota['avisos'].append('nota já importada — será ignorada')
            notas.append(nota)

            for it in nota['itens']:
                existente = _buscar_produto(it['ean'], it['nome'])
                categoria = (existente or {}).get('categoria')
                margem = _margem_categoria(categoria)
                custo = it['custo_unitario']
                sugerido = round(custo * (1 + margem / 100.0), 2) if custo > 0 else None
                perecivel = bool((existente or {}).get('perecivel'))
                avisos = []
                if it['quantidade'] <= 0:
                    avisos.append('quantidade zerada')
                if custo <= 0:
                    avisos.append('sem custo')
                if existente:
                    acao = 'atualizar'
                    if perecivel:
                        avisos.append('perecível: informe a validade do lote')
                else:
                    acao = 'cadastrar'
                    avisos.append('produto novo')
                if nota['duplicada']:
                    avisos.append('nota duplicada')
                itens.append({
                    **it,
                    'acao': acao,
                    'produto_id': (existente or {}).get('id'),
                    'categoria': categoria,
                    'margem': margem,
                    'preco_venda_sugerido': sugerido,
                    'perecivel': perecivel,
                    'validade': None,
                    'duplicada': nota['duplicada'],
                    'fornecedor': nota['fornecedor'],
                    'documento': nota['numero'],
                    'nota': nota,
                    'avisos': avisos,
                })

    validos = [i for i in itens if not i['duplicada']]
    total_custo = round(sum(i['custo_unitario'] * i['quantidade'] for i in validos), 2)
    return {
        'arquivos': arquivos,
        'notas': notas,
        'itens': itens,
        'total_itens': len(itens),
        'total_notas': len(notas),
        'notas_novas': sum(1 for n in notas if not n['duplicada']),
        'itens_novos': len(validos),
        'precisa_vencimento': any(n['vencimento'] is None and not n['duplicada'] for n in notas),
        'precisa_forma': any(n['forma'] is None and not n['duplicada'] for n in notas),
        'tem_perecivel': any(i['perecivel'] and not i['duplicada'] for i in itens),
        'total_custo': total_custo,
        'fornecedores': sorted({n['fornecedor'] for n in notas}),
    }


# ---------------------------------------------------------------------------
# Aplicacao
# ---------------------------------------------------------------------------
def _backup():
    """Backup consistente antes de gravar, usando a API de backup do SQLite
    (não copia o arquivo vivo, que poderia pegar um estado parcial)."""
    pasta = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), 'backups')
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f'mercadinho_antes_nfe_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    origem = sqlite3.connect(db.DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
        if copia.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup não íntegro antes da importação.')
    finally:
        origem.close()
        copia.close()
    return destino


def _remover_produtos_orfaos(ids):
    """Remove produtos recém-cadastrados que ficaram sem uso após uma falha na
    importação da nota — sem estoque e sem nenhuma referência (venda, compra,
    consumo, receita ou lote). Evita cadastros órfãos deixados por engano."""
    ids = [i for i in set(ids) if i]
    if not ids:
        return
    conn = db.get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        for pid in ids:
            p = conn.execute('SELECT quantidade_estoque FROM produtos WHERE id=?', (pid,)).fetchone()
            if not p or (p['quantidade_estoque'] or 0) > 0:
                continue
            if conn.execute('SELECT 1 FROM itens_compra WHERE produto_id=?', (pid,)).fetchone():
                continue
            if conn.execute('SELECT 1 FROM itens_venda WHERE produto_id=?', (pid,)).fetchone():
                continue
            if conn.execute('SELECT 1 FROM itens_consumo_interno WHERE produto_id=?', (pid,)).fetchone():
                continue
            if conn.execute('SELECT 1 FROM receita_itens WHERE insumo_id=?', (pid,)).fetchone():
                continue
            if conn.execute('SELECT 1 FROM lotes_validade WHERE produto_id=? AND quantidade>0', (pid,)).fetchone():
                continue
            conn.execute('DELETE FROM movimentacoes_estoque WHERE produto_id=?', (pid,))
            conn.execute('DELETE FROM lotes_validade WHERE produto_id=?', (pid,))
            conn.execute('DELETE FROM produtos WHERE id=?', (pid,))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def aplicar(caminho, plano=None, aplicar_preco_existentes=False,
            vencimento_padrao=None, forma_padrao=None, validade_padrao=None):
    """Grava a entrada das notas. Faz backup consistente antes. Devolve um resumo.

    Dados que a nota não traz (vencimento/condição de pagamento, validade de
    perecíveis) precisam ser informados explicitamente em `vencimento_padrao`,
    `forma_padrao` e `validade_padrao`; nunca são inventados."""
    import gestao as g

    plano = plano or pre_visualizar(caminho)

    # 0) Confere o que é indispensável ANTES de tocar no banco.
    for nota in plano['notas']:
        if nota.get('duplicada'):
            continue
        nota['_vencimento'] = nota.get('vencimento') or vencimento_padrao
        nota['_forma'] = nota.get('forma') or forma_padrao
        if not nota['_vencimento']:
            raise ValueError(
                f"Nota {nota['numero']} ({nota['fornecedor']}) sem vencimento conhecido. "
                'Informe a condição de pagamento (vencimento) antes de importar.')
        if nota['_forma'] not in ('A prazo', 'À vista'):
            raise ValueError(
                f"Nota {nota['numero']} ({nota['fornecedor']}) sem condição de pagamento. "
                'Escolha "A prazo" ou "À vista" antes de importar.')
    for it in plano['itens']:
        if it.get('duplicada'):
            continue
        it['validade'] = it.get('validade') or (validade_padrao if it.get('perecivel') else None)
        if it.get('perecivel') and not it['validade']:
            raise ValueError(
                f"Item perecível {it['nome']} sem validade. Informe a validade do lote "
                'antes de importar (a NF-e não traz essa data).')

    backup = _backup()
    cadastrados, avisos_gerais = [], []

    # 1) cadastra produtos novos (estoque zero; a nota da a entrada)
    mapa_cad = {}
    for it in plano['itens']:
        if it.get('duplicada') or it['acao'] != 'cadastrar':
            continue
        chave = it['ean'] or ('nome:' + it['nome'].strip().upper())
        if chave in mapa_cad:
            it['produto_id'] = mapa_cad[chave]
            continue
        preco_venda = it['preco_venda_sugerido'] or it['custo_unitario']
        try:
            pid = op.criar_produto(
                it['nome'], codigo_barras=it['ean'] or None, categoria=it['categoria'],
                unidade=it['unidade'], preco_custo=it['custo_unitario'],
                preco_venda=preco_venda, quantidade_estoque=0,
                estoque_minimo=2 if it['unidade'] == 'KG' else 5)
            mapa_cad[chave] = pid
            it['produto_id'] = pid
            cadastrados.append(it['nome'])
        except Exception as exc:
            avisos_gerais.append(f"{it['nome']}: {exc}")
            it['produto_id'] = None

    # 2) agrupa por nota e recebe a compra (estoque + custo medio + historico + a pagar)
    for nota in plano['notas']:
        if nota.get('duplicada'):
            avisos_gerais.append(f"Nota {nota['numero']} ({nota['fornecedor']}): já importada — ignorada.")
            continue
        itens_nota, criados_nota = [], []
        for it in plano['itens']:
            if it['nota'] is not nota or not it['produto_id']:
                continue
            if it['acao'] == 'cadastrar':
                criados_nota.append(it['produto_id'])
            itens_nota.append({
                'produto_id': it['produto_id'],
                'quantidade': it['quantidade'],
                'custo': it['custo_unitario'],
                'validade': it['validade'],
            })
        if not itens_nota:
            avisos_gerais.append(f"Nota {nota['numero']} ({nota['fornecedor']}): sem itens validos.")
            continue
        try:
            g.receber_compra(
                itens_nota, nota['fornecedor'], nota['numero'], nota['_vencimento'],
                nota['_forma'], chave='nfe_' + (nota['chave'] or nota['numero']))
        except Exception as exc:
            avisos_gerais.append(f"Nota {nota['numero']} ({nota['fornecedor']}): {exc}")
            _remover_produtos_orfaos(criados_nota)

    # 3) preco de venda sugerido nos produtos que ja existiam (opcional)
    if aplicar_preco_existentes:
        for it in plano['itens']:
            if it.get('duplicada'):
                continue
            if it['acao'] == 'atualizar' and it['produto_id'] and it['preco_venda_sugerido']:
                try:
                    op.atualizar_produto(it['produto_id'], preco_venda=it['preco_venda_sugerido'])
                except Exception:
                    pass

    return {
        'backup': backup,
        'notas': plano.get('notas_novas', plano['total_notas']),
        'cadastrados': cadastrados,
        'total_custo': plano['total_custo'],
        'avisos': avisos_gerais,
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Uso: python importar_nfe.py caminho/da/nota.xml [mais.xml ...]')
        sys.exit(1)
    db.init_db()
    plano = pre_visualizar(sys.argv[1:])
    print(f"{plano['total_notas']} nota(s), {plano['total_itens']} item(ns), "
          f"custo total R$ {plano['total_custo']:.2f}")
    for it in plano['itens']:
        print(f"  [{it['acao']:10}] {it['nome']:40} {it['quantidade']:>8} {it['unidade']:3} "
              f"custo {it['custo_unitario']:.2f} -> venda {it['preco_venda_sugerido']}")
