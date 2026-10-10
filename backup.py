import os
import shutil
import csv
import json
import sqlite3
from datetime import datetime, timedelta
import database as db

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR=os.path.join(BASE_DIR,'backups')
FIADO_DIR=os.path.join(BACKUP_DIR,'fiado_30min')
CONFIG_PATH=os.path.join(BASE_DIR,'config.json')
RETENCAO_PADRAO=30


def retencao_backups():
    """Quantos backups diários manter (config 'backup_retencao_dias')."""
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            valor = json.load(f).get('backup_retencao_dias', RETENCAO_PADRAO)
        return max(1, int(valor))
    except Exception:
        return RETENCAO_PADRAO


def _podar_backups_diarios(retencao=None):
    """Remove os backups diários mais antigos, mantendo os N mais recentes."""
    retencao = retencao or retencao_backups()
    try:
        arquivos = sorted(
            (n for n in os.listdir(BACKUP_DIR)
             if n.startswith('mercadinho_') and n.endswith('.db') and 'antes_' not in n),
            reverse=True)
    except OSError:
        return []
    removidos = []
    for nome in arquivos[retencao:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, nome))
            removidos.append(nome)
        except OSError:
            pass
    return removidos


def backup_diario(silencioso=True):
    os.makedirs(BACKUP_DIR,exist_ok=True)
    nome=f'mercadinho_{datetime.now().strftime("%Y-%m-%d")}.db'
    destino=os.path.join(BACKUP_DIR,nome)
    if os.path.exists(destino):
        return destino,False
    origem=sqlite3.connect(db.DB_PATH)
    copia=sqlite3.connect(destino)
    try:
        origem.backup(copia)
        if copia.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('Falha na verificação do backup.')
    finally:
        origem.close(); copia.close()
    _podar_backups_diarios()
    return destino,True


def backup_completo():
    from pathlib import Path
    pasta=Path(BACKUP_DIR)/('completo_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    pasta.mkdir(parents=True)
    origem=sqlite3.connect(db.DB_PATH); copia=sqlite3.connect(str(pasta/'mercadinho.db'))
    try:
        origem.backup(copia)
        if copia.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Backup não íntegro.')
    finally: origem.close(); copia.close()
    for nome in ('config.json',):
        arq=Path(BASE_DIR)/nome
        if arq.exists(): shutil.copy2(arq,pasta/nome)
    for nome in ('comprovantes','recibos'):
        arq=Path(BASE_DIR)/nome
        if arq.exists(): shutil.copytree(arq,pasta/nome)
    return pasta


def validar_banco(caminho):
    """Confere se o arquivo é um banco SQLite íntegro deste sistema."""
    c = sqlite3.connect(f'file:{os.path.abspath(caminho)}?mode=ro', uri=True)
    try:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup inválido (falha na verificação de integridade).')
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='produtos'").fetchone():
            raise RuntimeError('O arquivo não é um banco deste sistema.')
    finally:
        c.close()


def restaurar_backup(caminho):
    """Restaura o banco a partir de um arquivo validado, guardando antes uma
    cópia completa do estado atual. Devolve o caminho da cópia de segurança."""
    validar_banco(caminho)
    seguranca = backup_completo()
    origem = sqlite3.connect(caminho)
    destino = sqlite3.connect(db.DB_PATH)
    try:
        origem.backup(destino)
        if destino.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('A restauração resultou num banco inconsistente.')
    finally:
        origem.close(); destino.close()
    return seguranca


def registrar_fiado_recente(janela_minutos=30):
    """Gera um arquivo legível com vendas fiadas dos últimos N minutos.
    Serve como cópia operacional; a informação oficial continua no SQLite.
    """
    os.makedirs(FIADO_DIR,exist_ok=True)
    agora=datetime.now()
    inicio=agora-timedelta(minutes=janela_minutos)
    conn=db.get_conn()
    try:
        rows=conn.execute('''SELECT v.id,v.data_hora,v.valor_total,c.id cliente_id,c.nome cliente_nome
                            FROM vendas v JOIN clientes c ON c.id=v.cliente_id
                            WHERE v.forma_pagamento='fiado'
                            AND datetime(v.data_hora)>=datetime(?)
                            ORDER BY v.data_hora''',(inicio.strftime('%Y-%m-%d %H:%M:%S'),)).fetchall()
    finally: conn.close()
    if not rows:
        return None
    stamp=agora.strftime('%Y-%m-%d_%H-%M-%S')
    caminho=os.path.join(FIADO_DIR,f'fiado_{stamp}.csv')
    with open(caminho,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f,delimiter=';')
        w.writerow(['Venda','Data/Hora','Cliente ID','Cliente','Valor'])
        for r in rows:
            w.writerow([r['id'],r['data_hora'],r['cliente_id'],r['cliente_nome'],f"{r['valor_total']:.2f}"])
    return caminho
