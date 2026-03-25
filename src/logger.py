import logging
import sys
from pathlib import Path

# Ensure logs directory exists
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Standard logging format
LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers if get_logger is called multiple times
    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(LOG_FORMAT))
        
        # File handler
        fh = logging.FileHandler(LOGS_DIR / "turbo_refi.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(LOG_FORMAT))
        
        logger.addHandler(ch)
        logger.addHandler(fh)
        
    return logger
