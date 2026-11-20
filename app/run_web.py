#!/usr/bin/env python
"""Spuštění webové aplikace: python app/run_web.py  (adresa a port viz WEB_HOST / WEB_PORT v .env)"""
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

if __name__ == "__main__":
    import uvicorn
    from services import config

    uvicorn.run(
        "web.main:app",
        app_dir=str(APP_DIR),
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
        # Za reverzní proxy (nginx) - důvěřovat hlavičkám X-Forwarded-* z localhostu
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        reload="--reload" in sys.argv,
    )
