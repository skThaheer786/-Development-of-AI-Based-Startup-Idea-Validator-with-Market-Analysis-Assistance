#!/usr/bin/env python
"""
Entry point to run the Startup Idea Validator AI application.
Usage:
    python run.py
"""
import sys
import logging
from app import create_app
from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
app = create_app()

if __name__ == "__main__":
    print(f"===========================================================")
    print(f"  Startup Idea Validator AI — Multi-Agent Validation Engine ")
    print(f"===========================================================")
    print(f"  Host: http://{Config.HOST}:{Config.PORT}")
    print(f"  Groq model: {Config.GROQ_MODEL}" + (f"  ({Config.MODEL_NOTE})" if Config.MODEL_NOTE else ""))
    print(f"  Groq API Configured: {bool(Config.GROQ_API_KEY)}")
    print(f"  Tavily API Configured: {bool(Config.TAVILY_API_KEY)}")
    print(f"  Active Model: {Config.GROQ_MODEL}")
    print(f"===========================================================\n")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
