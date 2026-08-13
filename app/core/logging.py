"""应用日志配置。"""

import logging
import logging.config
import sys


def configure_logging(log_level: str = "INFO") -> None:
    """使用标准库初始化统一的控制台日志格式。"""
    normalized_level = log_level.upper()
    if normalized_level not in logging.getLevelNamesMapping():
        normalized_level = "INFO"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": ("%(asctime)s | %(levelname)s | %(name)s | %(message)s"),
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": sys.stdout,
                }
            },
            "root": {
                "handlers": ["console"],
                "level": normalized_level,
            },
        }
    )
