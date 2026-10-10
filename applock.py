"""Trava de instância única, multiplataforma (Windows e Linux).

Duas cópias do sistema acessando o mesmo SQLite fazem as operações travarem
(espera de lock). Este módulo garante que só exista uma instância aberta,
usando o mecanismo nativo de cada sistema:

* Windows: ``msvcrt.locking`` (lock de 1 byte no início do arquivo);
* Linux/macOS: ``fcntl.flock``.

O arquivo de trava fica no diretório temporário do sistema e guarda o PID da
instância ativa (apenas informativo). Se a instância cair, o lock é liberado
pelo sistema operacional automaticamente.
"""
from __future__ import annotations

import os
import tempfile


class InstanciaJaAberta(Exception):
    """Levantada quando já existe outra instância do sistema em execução."""


class TravaInstancia:
    def __init__(self, nome: str = 'mercadinho'):
        self.caminho = os.path.join(tempfile.gettempdir(), f'{nome}.lock')
        self._arquivo = None

    def adquirir(self):
        """Tenta tomar a trava. Levanta InstanciaJaAberta se já houver dono."""
        self._arquivo = open(self.caminho, 'a+')
        try:
            self._arquivo.seek(0, os.SEEK_END)
            if self._arquivo.tell() == 0:
                self._arquivo.write('0')
                self._arquivo.flush()
            self._arquivo.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self._arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                self._arquivo.close()
            except Exception:
                pass
            self._arquivo = None
            raise InstanciaJaAberta()
        self._gravar_pid()
        return self

    def _gravar_pid(self):
        try:
            self._arquivo.seek(0)
            self._arquivo.truncate()
            self._arquivo.write(str(os.getpid()))
            self._arquivo.flush()
        except Exception:
            pass

    def liberar(self):
        if not self._arquivo:
            return
        try:
            self._arquivo.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self._arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._arquivo.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._arquivo.close()
        except Exception:
            pass
        self._arquivo = None

    def __enter__(self):
        return self.adquirir()

    def __exit__(self, *exc):
        self.liberar()
        return False
