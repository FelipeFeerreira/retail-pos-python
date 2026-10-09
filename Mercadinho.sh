#!/usr/bin/env bash
# Launcher do Sistema do Mercadinho (retail-pos-python) para Ubuntu/Linux.
# Inicia o app usando o ambiente virtual do proprio projeto.
export XMODIFIERS=@im=none   # evita a lentidao do XIM/IBus no Tkinter
DIR="/home/emporio-ferreira/orca/retail-pos-python"
cd "$DIR" || exit 1
exec "$DIR/.venv/bin/python" "$DIR/app.py"
