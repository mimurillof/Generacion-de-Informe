"""
Configuración centralizada para el sistema de generación de informes.

Este módulo proporciona configuraciones por defecto y utilidades para
manejar variables de entorno de forma centralizada.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # Cargar variables de entorno automáticamente
except ImportError:
    pass  # python-dotenv es opcional


class Config:
    """Configuración centralizada del sistema."""
    
    # Configuración de Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "portfolio-files")
    SUPABASE_BASE_PREFIX = os.getenv("SUPABASE_BASE_PREFIX", "Graficos")
    ENABLE_SUPABASE_UPLOAD = os.getenv("ENABLE_SUPABASE_UPLOAD", "true").lower() == "true"
    SUPABASE_CLEANUP_AFTER_TESTS = os.getenv("SUPABASE_CLEANUP_AFTER_TESTS", "false").lower() == "true"
    
    # Configuración de PDF
    PDF_PAGE_SIZE = "A4"
    PDF_DEFAULT_FONT = "Helvetica"
    PDF_DEFAULT_FONT_SIZE = 10
    
    # Configuración de logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def get_supabase_key(cls) -> str:
        """Obtiene la clave de Supabase apropiada (service role o anon)."""
        return cls.SUPABASE_SERVICE_ROLE_KEY or cls.SUPABASE_ANON_KEY or ""
    
    @classmethod
    def validate_supabase_config(cls) -> bool:
        """Valida que la configuración de Supabase esté completa."""
        return bool(cls.SUPABASE_URL and cls.get_supabase_key())
    
    @classmethod
    def get_default_image_config(cls, path: str, **kwargs) -> Dict[str, Any]:
        """
        Genera una configuración por defecto para descarga de imágenes.
        
        Args:
            path: Ruta de la imagen en Supabase
            **kwargs: Configuraciones adicionales que sobrescriben los valores por defecto
        
        Returns:
            Diccionario con configuración completa para descarga de imagen
        """
        config = {
            "bucket": cls.SUPABASE_BUCKET_NAME,
            "path": f"{cls.SUPABASE_BASE_PREFIX}/{path}".strip("/"),
            "public": True,
            "use_url": False,
        }
        config.update(kwargs)
        return config


def setup_logging(level: Optional[str] = None) -> None:
    """Configura el sistema de logging."""
    import logging
    
    log_level = level or Config.LOG_LEVEL
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def get_project_root() -> Path:
    """Obtiene la ruta raíz del proyecto."""
    return Path(__file__).parent


def ensure_directory(path: Path) -> Path:
    """Asegura que un directorio exista, creándolo si es necesario."""
    path.mkdir(parents=True, exist_ok=True)
    return path