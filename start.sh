#!/usr/bin/env bash
# OmniWarRoom AI — local startup script
set -e

# Ensure data directory exists
mkdir -p data
mkdir -p ui/static

# Start Streamlit
streamlit run ui/app.py
