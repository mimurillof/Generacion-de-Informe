import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, cast

import requests

try:
    from config import Config
except ImportError:
    # Fallback si config.py no está disponible
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    class Config:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "portfolio-files")
        
        @classmethod
        def get_supabase_key(cls):
            return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or ""
        
        @classmethod
        def validate_supabase_config(cls):
            return bool(cls.SUPABASE_URL and cls.get_supabase_key())

try:
    from supabase import create_client, Client
except Exception:  # pragma: no cover - dependency may not be installed yet
    create_client = None  # type: ignore
    Client = Any  # type: ignore


_SUPABASE_CLIENT: Optional["Client"] = None


def get_supabase_client() -> "Client":
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is not None:
        return _SUPABASE_CLIENT

    if not Config.validate_supabase_config():
        raise EnvironmentError(
            "Variables de entorno SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY requeridas para usar Supabase. "
            "Verifica tu archivo .env o las variables de entorno del sistema."
        )
    
    if create_client is None:
        raise RuntimeError("La librería 'supabase' no está instalada. Ejecuta: pip install -r requirements.txt")
    
    _SUPABASE_CLIENT = create_client(cast(str, Config.SUPABASE_URL), Config.get_supabase_key())
    return _SUPABASE_CLIENT


def create_image_config(path: str, **kwargs) -> Dict[str, Any]:
    """
    Crea una configuración de imagen usando valores por defecto del entorno.
    
    Args:
        path: Ruta de la imagen (se prefijará automáticamente con SUPABASE_BASE_PREFIX)
        **kwargs: Configuraciones adicionales que sobrescriben los valores por defecto
    
    Returns:
        Diccionario con configuración completa para download_image_from_supabase
    
    Example:
        config = create_image_config("portfolio_growth.png")
        # Resulta en: {"bucket": "portfolio-files", "path": "Graficos/portfolio_growth.png", ...}
    """
    try:
        return Config.get_default_image_config(path, **kwargs)
    except NameError:
        # Fallback si Config no está disponible
        prefix = os.getenv("SUPABASE_BASE_PREFIX", "Graficos")
        config = {
            "bucket": os.getenv("SUPABASE_BUCKET_NAME", "portfolio-files"),
            "path": f"{prefix}/{path}".strip("/"),
            "public": True,
            "use_url": False,
        }
        config.update(kwargs)
        return config


def download_image_from_supabase(image_config: Dict[str, Any]) -> Optional[Path]:
    """
    Descarga una imagen desde Supabase Storage y devuelve la ruta del archivo temporal.

    Formatos soportados en image_config:
    {
      "bucket": "portfolio-files",    # opcional; usa SUPABASE_BUCKET_NAME si no se especifica
      "path": "charts/portfolio_growth.png",
      "public": true,              # opcional (por defecto False)
      "expires_in": 3600,          # opcional para URL firmada
      "use_url": false,            # opcional; si True, usa URL y streaming por chunks
      "transform": {               # opcional; se aplica cuando se usa descarga directa
        "width": 1000,
        "height": 800,
        "quality": 80,
        "resize": "cover",       # cover|contain|fill
        "format": "origin"        # origin|avif
      }
    }
    """
    try:
        client = get_supabase_client()
        
        # Usar variables de entorno por defecto si no se especifican
        bucket = image_config.get("bucket") or Config.SUPABASE_BUCKET_NAME
        path = image_config.get("path")
        
        if not bucket or not path:
            raise ValueError("'bucket' y 'path' son requeridos para descargar imagen desde Supabase. "
                           "Especifica 'bucket' en image_config o define SUPABASE_BUCKET_NAME en las variables de entorno.")
        
        use_url = bool(image_config.get("use_url", False))
        transform = image_config.get("transform")

        if not use_url:
            # Descarga directa vía SDK (retorna bytes). Aplica transformaciones si están definidas
            if transform and isinstance(transform, dict):
                resp_bytes = client.storage.from_(bucket).download(path, {"transform": transform})
            else:
                resp_bytes = client.storage.from_(bucket).download(path)

            suffix = Path(path).suffix or ".png"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            with open(temp_file.name, "wb") as f:
                f.write(resp_bytes)
            temp_path = Path(temp_file.name)
            logging.info("Imagen descargada (SDK) desde Supabase: %s -> %s", path, temp_path)
            return temp_path
        else:
            # Descargar vía URL con streaming por chunks (menos RAM). Útil si quieres trazabilidad HTTP
            if image_config.get("public", False):
                url = client.storage.from_(bucket).get_public_url(path)
            else:
                expires_in = image_config.get("expires_in", 3600)
                url = client.storage.from_(bucket).create_signed_url(path, expires_in)
                if isinstance(url, dict) and "signedURL" in url:
                    url = url["signedURL"]

            with requests.get(url, timeout=60, stream=True) as response:
                response.raise_for_status()
                suffix = Path(path).suffix or ".png"
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                with open(temp_file.name, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                temp_path = Path(temp_file.name)
                logging.info("Imagen descargada (URL-stream) desde Supabase: %s -> %s", path, temp_path)
                return temp_path
        
    except Exception as exc:
        logging.error("Error descargando imagen desde Supabase %s/%s: %s", 
                     image_config.get("bucket", ""), image_config.get("path", ""), exc)
        return None


def cleanup_temp_files(temp_files: list[Path]) -> None:
    """Limpia archivos temporales descargados."""
    if not temp_files:
        return
        
    cleaned_count = 0
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                temp_file.unlink()
                logging.debug("Archivo temporal eliminado: %s", temp_file)
                cleaned_count += 1
        except Exception as exc:
            logging.warning("No se pudo eliminar archivo temporal %s: %s", temp_file, exc)
    
    if cleaned_count > 0:
        logging.info("Limpiados %d archivos temporales de Supabase", cleaned_count)


def cleanup_temp_files_if_enabled(temp_files: list[Path]) -> None:
    """
    Limpia archivos temporales solo si está habilitado en la configuración.
    Usa la variable de entorno SUPABASE_CLEANUP_AFTER_TESTS.
    """
    try:
        should_cleanup = Config.SUPABASE_CLEANUP_AFTER_TESTS
    except NameError:
        # Fallback si Config no está disponible
        should_cleanup = os.getenv("SUPABASE_CLEANUP_AFTER_TESTS", "false").lower() == "true"
    
    if should_cleanup:
        cleanup_temp_files(temp_files)
        logging.info("Limpieza automática completada (habilitada por configuración)")
    else:
        logging.debug("Limpieza automática omitida (deshabilitada por configuración)")


def download_json_structure_from_supabase(
    json_filename: str = "estructura_informe.json",
    local_fallback_path: Optional[str] = None,
    user_id: Optional[str] = None  # ✅ NUEVO: Requerido para multiusuario
) -> Path:
    """
    Descarga el archivo JSON de estructura del informe desde Supabase.
    
    Args:
        json_filename: Nombre del archivo JSON en Supabase
        local_fallback_path: Ruta local alternativa si falla la descarga
        user_id: ID del usuario propietario del JSON (requerido para multiusuario)
        
    Returns:
        Path: Ruta al archivo JSON descargado (temporal) o local fallback
        
    Raises:
        FileNotFoundError: Si no se puede descargar ni encontrar archivo local
        ValueError: Si user_id no se proporciona
    """
    if not user_id:
        raise ValueError("user_id es requerido para descargar JSON de Supabase en modo multiusuario")
    
    try:
        client = get_supabase_client()
        bucket = client.storage.from_(Config.SUPABASE_BUCKET_NAME)
        
        # Construir la ruta en Supabase: {user_id}/estructura_informe.json (✅ MULTIUSUARIO)
        supabase_path = f"{user_id}/{json_filename}"
        
        logging.info(f"🔽 Descargando JSON desde Supabase: {supabase_path}")
        
        # Descargar el archivo
        response = bucket.download(supabase_path)
        
        if not response:
            raise Exception("Respuesta vacía de Supabase")
        
        # Crear archivo temporal
        temp_file = tempfile.NamedTemporaryFile(
            mode='w+b',
            suffix='.json',
            prefix='tmp_report_structure_',
            delete=False
        )
        
        try:
            temp_file.write(response)
            temp_file.flush()
            temp_path = Path(temp_file.name)
            
            logging.info(f"✅ JSON descargado exitosamente: {temp_path}")
            logging.info(f"📊 Tamaño del archivo: {len(response)} bytes")
            
            return temp_path
            
        finally:
            temp_file.close()
            
    except Exception as e:
        logging.warning(f"⚠️ Error descargando JSON desde Supabase: {e}")
        
        # Intentar fallback local si está disponible
        if local_fallback_path and os.path.exists(local_fallback_path):
            logging.info(f"🔄 Usando archivo local como fallback: {local_fallback_path}")
            return Path(local_fallback_path)
        
        # Si no hay fallback, intentar en el directorio actual
        current_dir_json = Path(json_filename)
        if current_dir_json.exists():
            logging.info(f"🔄 Usando archivo en directorio actual: {current_dir_json}")
            return current_dir_json
        
        raise FileNotFoundError(
            f"No se pudo descargar '{supabase_path}' desde Supabase "
            f"y no se encontró archivo local en '{local_fallback_path or json_filename}'"
        )


def upload_pdf_to_supabase(
    local_pdf_path: Path,
    remote_filename: str = "Reporte.pdf",
    remote_folder: Optional[str] = None,  # ✅ MODIFICADO: Ahora opcional
    user_id: Optional[str] = None  # ✅ NUEVO: Requerido para multiusuario
) -> Dict[str, Any]:
    """
    Sube un archivo PDF a Supabase Storage usando upsert=True.
    
    Args:
        local_pdf_path: Ruta local al archivo PDF
        remote_filename: Nombre del archivo en Supabase (sin versiones)
        remote_folder: (DEPRECATED) Carpeta destino - se ignora en modo multiusuario
        user_id: ID del usuario propietario del PDF (requerido para multiusuario)
        
    Returns:
        Dict con información de la subida (success, url, etc.)
        
    Raises:
        FileNotFoundError: Si el archivo local no existe
        ValueError: Si user_id no se proporciona
        Exception: Si falla la subida a Supabase
    """
    if not local_pdf_path.exists():
        raise FileNotFoundError(f"Archivo PDF no encontrado: {local_pdf_path}")
    
    if not user_id:
        raise ValueError("user_id es requerido para subir PDF a Supabase en modo multiusuario")
    
    try:
        client = get_supabase_client()
        bucket = client.storage.from_(Config.SUPABASE_BUCKET_NAME)
        
        # Construir la ruta remota: {user_id}/Reporte.pdf (✅ MULTIUSUARIO)
        remote_path = f"{user_id}/{remote_filename}".strip("/")
        
        # Obtener tamaño del archivo
        file_size = local_pdf_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        logging.info(f"📤 Subiendo PDF a Supabase: {remote_path}")
        logging.info(f"📊 Tamaño del archivo: {file_size:,} bytes ({file_size_mb:.2f} MB)")
        
        # Abrir archivo y subir con upsert=True
        with open(local_pdf_path, "rb") as f:
            file_options = {
                "content-type": "application/pdf",
                "upsert": "true"  # Debe ser string, no bool
            }
            
            response = bucket.upload(remote_path, f, file_options)
            
            logging.info(f"✅ PDF subido exitosamente a Supabase: {remote_path}")
            
            # Obtener URL pública para verificación
            try:
                public_url = bucket.get_public_url(remote_path)
                logging.info(f"🔗 URL pública: {public_url}")
            except Exception:
                public_url = None
                logging.debug("URL pública no disponible (bucket privado)")
            
            return {
                "success": True,
                "remote_path": remote_path,
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size_mb, 2),
                "response": response,
                "public_url": public_url
            }
            
    except Exception as e:
        logging.error(f"❌ Error subiendo PDF a Supabase: {e}")
        raise Exception(f"Falló la subida del PDF a Supabase: {e}")


def get_temp_files_stats() -> Dict[str, Any]:
    """Obtiene estadísticas sobre archivos temporales del sistema."""
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    
    # Buscar archivos temporales relacionados con nuestro sistema
    temp_patterns = ["tmp*supabase*", "tmp*.png", "tmp*.jpg", "tmp*.jpeg", "tmp*report_structure*"]
    total_files = 0
    total_size = 0
    
    for pattern in temp_patterns:
        for temp_file in temp_dir.glob(pattern):
            if temp_file.is_file():
                try:
                    size = temp_file.stat().st_size
                    total_files += 1
                    total_size += size
                except Exception:
                    pass  # Ignorar archivos que no se pueden acceder
    
    return {
        "temp_directory": str(temp_dir),
        "total_temp_files": total_files,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2)
    }


