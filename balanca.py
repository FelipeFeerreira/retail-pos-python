"""
Integração com balanças Toledo para checkout.

Perfil principal: Toledo 8217 (linha Prix / checkout).

Protocolos suportados pela 8217 (manual Toledo):
  * P05A  -> ENQ -> [STX][PPPPP][ETX]; PPPPP = 5 dígitos sem ponto decimal
             (2 primeiros = parte inteira, 3 últimos = decimais).
  * P05B  -> ENQ -> [STX][S][PPDPPP][ETX]; S = espaço (positivo) ou '-' e
             PPDPPP = 6 caracteres com ponto decimal (ex.: "00.185").
  * P05   -> modo antigo, tratado como P05A (por demanda).
  * P06   -> saída contínua [STX][PP.DDD][CR] (ex.: "00.185").
  * Genérico -> tenta achar um peso em texto livre.

Comunicação serial: 8 bits de dados, sem paridade, 1 stop bit. A velocidade
na 8217 é configurável (C10), com padrão de fábrica 2400 bauds — por isso o
baud rate é ajustável na tela de configuração.

Este módulo mantém um leitor em thread separada para não travar a interface
Tkinter, e expõe os bytes crus recebidos (diagnóstico) para ajudar a achar a
configuração certa quando a balança não responde.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Optional, Callable

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


# Modos: p05a/p05b/p05 -> enviam ENQ; p06/generic -> leitura contínua.
PROTOCOLOS = {
    "P05A (Toledo 8217)": {"baudrate": 2400, "parity": "N", "mode": "p05a"},
    "P05B (Toledo 8217)": {"baudrate": 2400, "parity": "N", "mode": "p05b"},
    "P05 (Toledo 8217)": {"baudrate": 2400, "parity": "N", "mode": "p05"},
    "P06 (Toledo 8217)": {"baudrate": 9600, "parity": "N", "mode": "p06"},
    "Genérico contínuo": {"baudrate": 9600, "parity": "N", "mode": "generic"},
}

BAUDRATES = [2400, 4800, 9600, 1200, 300]
PARIDADES = {"N": "Nenhuma", "E": "Par", "O": "Ímpar"}


class LeitorBalanca:
    """Leitor de balança Toledo/serial sem bloquear a interface Tkinter."""

    PROTOCOLOS = PROTOCOLOS
    BAUDRATES = BAUDRATES
    PARIDADES = PARIDADES

    def __init__(
        self,
        porta: Optional[str] = None,
        baudrate: int = 2400,
        callback_peso: Optional[Callable[[float], None]] = None,
        protocolo: str = "P05A (Toledo 8217)",
        demanda: bool = True,
        parity: str = "N",
        callback_bruto: Optional[Callable[[bytes], None]] = None,
    ):
        self.porta = porta
        self.baudrate = int(baudrate)
        self.parity = str(parity or "N").upper()[:1]
        self.callback_peso = callback_peso
        self.callback_bruto = callback_bruto
        self.protocolo = protocolo
        self.demanda = demanda
        cfg = PROTOCOLOS.get(protocolo, {})
        self.mode = cfg.get("mode", "generic")
        self._serial = None
        self._thread = None
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._ultimo_peso = 0.0
        self._ultimo_recebimento = 0.0
        self._ultimo_bruto = b""
        self._erro = None
        self._buffer = b""

    @staticmethod
    def portas_disponiveis():
        if list_ports is None:
            return []
        return [
            {
                "device": p.device,
                "descricao": p.description or p.device,
                "hwid": p.hwid or "",
            }
            for p in list_ports.comports()
        ]

    @classmethod
    def criar_para_toledo_8217(cls, porta: str, protocolo="P05A (Toledo 8217)",
                               callback_peso=None, baudrate=None, parity=None,
                               callback_bruto=None):
        cfg = PROTOCOLOS.get(protocolo, PROTOCOLOS["P05A (Toledo 8217)"])
        return cls(
            porta=porta,
            baudrate=int(baudrate) if baudrate else cfg["baudrate"],
            parity=(parity or cfg.get("parity", "N")),
            callback_peso=callback_peso,
            callback_bruto=callback_bruto,
            protocolo=protocolo,
            demanda=cfg["mode"] in ("p05a", "p05b", "p05"),
        )

    @property
    def conectado(self):
        return self._serial is not None and self._serial.is_open

    @property
    def erro(self):
        return self._erro

    @property
    def ultimo_bruto(self):
        with self._lock:
            return self._ultimo_bruto

    def peso_atual(self) -> float:
        with self._lock:
            return self._ultimo_peso

    def leitura_recente(self, segundos=2.0) -> bool:
        with self._lock:
            return self._ultimo_recebimento > 0 and (time.time() - self._ultimo_recebimento) <= segundos

    def iniciar(self):
        self.parar()
        self._erro = None
        self._buffer = b""
        if serial is None:
            self._erro = "PySerial não está instalado. Rode: pip install pyserial"
            return False
        if not self.porta:
            self._erro = "Nenhuma porta COM foi selecionada."
            return False

        paridade = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }.get(self.parity, serial.PARITY_NONE)

        try:
            self._serial = serial.Serial(
                port=self.porta,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=paridade,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.12,
                write_timeout=0.3,
            )
        except Exception as exc:
            self._serial = None
            self._erro = f"Não foi possível abrir {self.porta}: {exc}"
            return False

        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="LeitorBalancaToledo")
        self._thread.start()
        return True

    def parar(self):
        self._parar.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.8)
        self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def solicitar_peso(self):
        """Envia ENQ para protocolos Toledo P05/P05A/P05B."""
        if not self.conectado:
            return False
        try:
            self._serial.write(b"\x05")
            return True
        except Exception as exc:
            self._erro = f"Falha ao solicitar peso: {exc}"
            return False

    def _loop(self):
        proxima_solicitacao = 0.0
        while not self._parar.is_set():
            try:
                agora = time.monotonic()
                if self.demanda and agora >= proxima_solicitacao:
                    self.solicitar_peso()
                    proxima_solicitacao = agora + 0.30

                dados = self._serial.read(64)
                if dados:
                    self._processar_bytes(dados)
            except Exception as exc:
                self._erro = f"Leitura da balança interrompida: {exc}"
                break

    def _processar_bytes(self, dados: bytes):
        with self._lock:
            self._ultimo_bruto = dados[-64:]
        if self.callback_bruto:
            try:
                self.callback_bruto(dados)
            except Exception:
                pass

        self._buffer += dados
        # Limita o buffer para não crescer em caso de protocolo incompatível.
        self._buffer = self._buffer[-256:]

        while True:
            inicio = self._buffer.find(b"\x02")  # STX
            if inicio < 0:
                # Sem STX (ex.: texto livre) tenta extrair um peso da mensagem.
                texto = self._buffer.decode("ascii", errors="ignore")
                peso = self._extrair_peso(texto)
                if peso is not None:
                    self._registrar_peso(peso)
                    self._buffer = b""
                return

            # Procura o terminador ETX (03) ou CR (0d) a partir do STX.
            fim = -1
            for i in range(inicio + 1, len(self._buffer)):
                if self._buffer[i] in (0x03, 0x0d):
                    fim = i
                    break
            if fim < 0:
                # Pacote ainda incompleto; espera mais bytes.
                if inicio > 0:
                    self._buffer = self._buffer[inicio:]
                return

            pacote = self._buffer[inicio:fim + 1]
            self._buffer = self._buffer[fim + 1:]
            peso = self._parsear_toledo_pacote(pacote)
            if peso is not None:
                self._registrar_peso(peso)

    @staticmethod
    def _parsear_toledo_pacote(pacote: bytes) -> Optional[float]:
        if len(pacote) < 4 or pacote[0] != 0x02:
            return None
        corpo = pacote[1:]
        if corpo and corpo[-1] in (0x03, 0x0d):
            corpo = corpo[:-1]
        texto = corpo.decode("ascii", errors="ignore")
        return LeitorBalanca._interpretar_corpo(texto)

    @staticmethod
    def _interpretar_corpo(texto: str) -> Optional[float]:
        t = texto.strip()
        if not t:
            return None
        # Instável / negativo / acima: corpo preenchido com a mesma letra.
        if len(t) >= 3 and len(set(t)) == 1 and t[0] in ("I", "N", "S"):
            return None
        # P05A: 5 dígitos sem ponto decimal -> 2 inteiros + 3 decimais.
        if re.fullmatch(r"\d{5}", t):
            return int(t[:2]) + int(t[2:]) / 1000.0
        # P05B / P06 (e "peso + tara"): número com ponto decimal.
        m = re.search(r"[-+]?\d+\.\d+", texto)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return LeitorBalanca._extrair_peso(texto)

    @staticmethod
    def _extrair_peso(texto: str) -> Optional[float]:
        s = texto.strip().replace(";", " ")
        encontrados = re.findall(
            r"([-+]?\d+(?:[.,]\d+)?)\s*(kg|kgs|quilograma|quilogramas|g|gr|gramas)\b",
            s,
            re.IGNORECASE,
        )
        if encontrados:
            numero, unidade = encontrados[-1]
            valor = float(numero.replace(",", "."))
            if unidade.lower().startswith(("g", "gr")):
                valor /= 1000.0
            return valor

        numeros = re.findall(r"[-+]?\d+(?:[.,]\d+)?", s)
        if len(numeros) == 1:
            try:
                return float(numeros[0].replace(",", "."))
            except ValueError:
                return None
        return None

    def _registrar_peso(self, peso: float):
        peso = round(max(0.0, float(peso)), 3)
        with self._lock:
            self._ultimo_peso = peso
            self._ultimo_recebimento = time.time()
        if self.callback_peso:
            try:
                self.callback_peso(peso)
            except Exception:
                pass
