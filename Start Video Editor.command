#!/bin/bash
# Double-click this file on a Mac to open the AI Video Editor panel.
cd "$(dirname "$0")" || exit 1
echo "AI Video Editor shuru ho raha hai..."
git pull --quiet 2>/dev/null && echo "Latest version le liya."
if [ ! -d .venv ]; then
  echo "Pehli baar setup ho raha hai (2-5 minute)..."
  PY=$(command -v python3.12 || echo /opt/homebrew/bin/python3.12)
  "$PY" -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt
fi
source .venv/bin/activate
pip install -q -r requirements.txt 2>/dev/null
echo ""
echo "Panel browser mein khul raha hai. Is window ko band mat karna (minimize kar sakte ho)."
echo "Band karne ke liye: Ctrl + C"
streamlit run app.py
