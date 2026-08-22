#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python gradio_app.py
