"""
Integração com balanças Toledo para checkout.

Perfil principal: Toledo 8217 (etiqueta do equipamento do projeto).

A 8217 suporta protocolos P05/P05A/P06 e comunicação serial. Para P05A,
o equipamento pode aguardar ENQ (ASCII 0x05) e responder com
STX + 5 caracteres de peso + ETX. O peso é enviado sem ponto decimal,
com os dois primeiros caracteres como parte inteira e os três últimos
como parte decimal.

Este módulo também mantém um modo genérico para balanças que enviam o
peso continuamente.
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


class LeitorBalanca:
    """Leitor de balança Toledo/serial sem bloquear a interface Tkinter."""

    PROTOCOLOS = {
        "P05A (Toledo 8217)": {"baudrate": 9600, "parity": "N", "mode": "p05a"},
        "P05 (Toledo 8217)": {"baudrate": 2400, "parity": "N", "mode": "p05"},
        "P06 (Toledo 8217)": {"baudrate": 9600, "parity": "N", "mode": "p06"},
        "Genérico contínuo": {"baudrate": 9600, "parity": "N", "mode": "generic"},
    }

    def __init__(
        self,
        porta: Optional[str] = None,
        baudrate: int = 9600,
        callback_peso: Optional[Callable[[float], None]] = None,
        protocolo: str = "P05A (Toledo 8217)",
        demanda: bool = True,
    ):
        self.porta = porta
        self.baudrate = int(baudrate)
        self.callback_peso = callback_peso
        self.protocolo = protocolo
        self.demanda = demanda
        self._serial = None
        self._thread = None
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._ultimo_peso = 0.0
        self._ultimo_recebimento = 0.0
        self._erro = None

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
    def criar_para_toledo_8217(cls, porta: str, protocolo="P05A (Toledo 8217)", callback_peso=None):
        cfg = cls.PROTOCOLOS.get(protocolo, cls.PROTOCOLOS["P05A (Toledo 8217)"])
        return cls(
            porta=porta,
            baudrate=cfg["baudrate"],
            callback_peso=callback_peso,
            protocolo=protocolo,
            demanda=cfg["mode"] in ("p05a", "p05"),
        )

    @property
    def conectado(self):
        return self._serial is not None and self._serial.is_open

    @property
    def erro(self):
        return self._erro

    def peso_atual(self) -> float:
        with self._lock:
            return self._ultimo_peso

    def leitura_recente(self, segundos=2.0) -> bool:
        with self._lock:
            return self._ultimo_recebimento > 0 and (time.time() - self._ultimo_recebimento) <= segundos

    def iniciar(self):
        self.parar()
        self._erro = None
        if serial is None:
            self._erro = "PySerial não está instalado. Rode: pip install pyserial"
            return False
        if not self.porta:
            self._erro = "Nenhuma porta COM foi selecionada."
            return False

        cfg = self.PROTOCOLOS.get(self.protocolo, {})
        baudrate = int(cfg.get("baudrate", self.baudrate))
        mode = cfg.get("mode", "generic")
        self.demanda = mode in ("p05a", "p05")

        try:
            self._serial = serial.Serial(
                port=self.porta,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
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
        """Envia ENQ para protocolos Toledo P05/P05A."""
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
        # P05/P05A: STX + 5 bytes + ETX. Pode chegar fragmentado em várias leituras.
        if hasattr(self, "_buffer"):
            self._buffer += dados
        else:
            self._buffer = dados

        # Limita o buffer para não crescer em caso de protocolo incompatível.
        self._buffer = self._buffer[-256:]

        while True:
            inicio = self._buffer.find(b"\x02")
            if inicio < 0:
                # P06/genérico pode não ter STX legível; tenta texto abaixo.
                texto = self._buffer.decode("ascii", errors="ignore")
                peso = self._extrair_peso(texto)
                if peso is not None:
                    self._registrar_peso(peso)
                    self._buffer = b""
                return

            if len(self._buffer) < inicio + 7:
                return

            fim = self._buffer.find(b"\x03", inicio + 1)
            if fim < 0:
                # P06 pode usar CR como final.
                cr = self._buffer.find(b"\x0d", inicio + 1)
                if cr >= 0:
                    pacote = self._buffer[inicio:cr + 1]
                    self._buffer = self._buffer[cr + 1:]
                    peso = self._parsear_toledo_pacote(pacote)
                    if peso is not None:
                        self._registrar_peso(peso)
                    continue
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
        corpo = pacote[1:-1].decode("ascii", errors="ignore").strip()
        if not corpo:
            return None
        if corpo[0] in ("I", "N", "S"):
            return None  # instável, negativo ou acima da capacidade

        # P05/P05A: 5 dígitos, dois inteiros + três decimais.
        if re.fullmatch(r"\d{5}", corpo):
            return int(corpo[:2]) + int(corpo[2:]) / 1000.0

        # P06: permite 00.000 ou outras representações textuais.
        return LeitorBalanca._extrair_peso(corpo)

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
