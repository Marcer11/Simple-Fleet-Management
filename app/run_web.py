#!/usr/bin/env python

import sys
from pathlib import Path

root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "web.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )
