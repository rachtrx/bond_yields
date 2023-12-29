import logging
from logging.handlers import RotatingFileHandler
import os

NO_CONTENT = 204
OK = 200

def setup_logger(_id):
    logger = logging.getLogger(f'logger_{_id}')

    # Check if the logger already has handlers set up
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        log_directory = "/var/log/indiv_logs/"
        os.makedirs(log_directory, exist_ok=True)

        log_filename = os.path.join(log_directory, f"{_id}.log")
        file_handler = RotatingFileHandler(log_filename, maxBytes=1000000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

def write_to_logfile(_id, log):
    logger = setup_logger(_id)
    logger.info(log)