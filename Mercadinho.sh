#!/usr/bin/env bash
# Launcher do Sistema do Mercadinho (retail-pos-python) para Linux/macOS.
# Inicia o app usando o ambiente virtual do proprio projeto, sem depender de
# caminho fixo: funciona em qualquer pasta onde o projeto esteja instalado.
set -e

# Evita a lentidao do XIM/IBus no Tkinter (sem metodo de entrada neste sistema).
export XMODIFIERS=@im=none

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -x "$DIR/.venv/bin/python" ]; then
    PY="$DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    PY="$(command -v python)"
fi

exec "$PY" "$DIR/app.py" "$@"
