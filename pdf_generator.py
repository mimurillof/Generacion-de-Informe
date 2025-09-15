import argparse
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from jsonschema import Draft7Validator, validate
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet, StyleSheet1
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

try:
    from dotenv import load_dotenv
    load_dotenv()  # Cargar variables de entorno automáticamente
except ImportError:
    pass  # python-dotenv es opcional

try:
    from data_sources import download_image_from_supabase, create_image_config, cleanup_temp_files, download_json_structure_from_supabase, upload_pdf_to_supabase
except ImportError:
    # Fallback si data_sources no está disponible
    download_image_from_supabase = None
    create_image_config = None
    cleanup_temp_files = None
    download_json_structure_from_supabase = None
    upload_pdf_to_supabase = None
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Local modules
from data_sources import download_image_from_supabase, cleanup_temp_files


class NumberedCanvas(Canvas):
    """Canvas that adds 'Page x of y' footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(page_count)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count: int) -> None:
        self.setFont("Helvetica", 9)
        page_str = f"Página {self._pageNumber} de {page_count}"
        width, height = A4
        self.drawRightString(width - 40, 20, page_str)


def load_json(json_path: Path) -> Dict[str, Any]:
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_json(instance: Dict[str, Any], schema_path: Optional[Path]) -> None:
    if not schema_path:
        return
    if not schema_path.exists():
        logging.warning("Schema no encontrado en %s, se continúa sin validación", schema_path)
        return
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        for err in errors:
            logging.error("JSON inválido en %s: %s", list(err.path), err.message)
        raise ValueError("El JSON de entrada no cumple el esquema. Revisa los errores de validación.")


def build_styles() -> StyleSheet1:
    styles = getSampleStyleSheet()

    # Create aliases for headings using add method
    styles.add(ParagraphStyle(name="Header1", parent=styles["Heading1"]))
    styles.add(ParagraphStyle(name="Header2", parent=styles["Heading2"]))
    styles.add(ParagraphStyle(name="Header3", parent=styles["Heading3"]))

    # Custom styles (using custom names to avoid conflicts)
    styles.add(ParagraphStyle(name="Body", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=14))
    styles.add(
        ParagraphStyle(name="BodyItalic", parent=styles["Body"], fontName="Helvetica-Oblique", fontSize=10, leading=14)
    )
    styles.add(ParagraphStyle(name="BodyBold", parent=styles["Body"], fontName="Helvetica-Bold", fontSize=10, leading=14))
    styles.add(
        ParagraphStyle(
            name="Centered", parent=styles["Body"], alignment=TA_CENTER, fontName="Helvetica", fontSize=10, leading=14
        )
    )
    styles.add(
        ParagraphStyle(
            name="Disclaimer", parent=styles["Body"], textColor=colors.grey, fontSize=8, leading=12, spaceBefore=6
        )
    )
    styles.add(ParagraphStyle(name="Caption", parent=styles["BodyItalic"], fontSize=8, leading=10, textColor=colors.grey))

    return styles


def to_inches(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value) * inch
    except Exception:
        return None


def resolve_paragraph_style(styles: StyleSheet1, style_key: Optional[str]) -> ParagraphStyle:
    if not style_key:
        return cast(ParagraphStyle, styles.byName["Body"])
    key_norm = style_key.strip().lower()
    mapping = {
        "body": "Body",
        "normal": "Body",
        "italic": "BodyItalic",
        "bold": "BodyBold",
        "centered": "Centered",
        "disclaimer": "Disclaimer",
        "caption": "Caption",
        "title": "Header1",
        "subtitle": "Header2",
    }
    resolved = mapping.get(key_norm)
    style_name = resolved or style_key
    return cast(ParagraphStyle, styles.byName.get(style_name, styles.byName["Body"]))


def render_header(element: Dict[str, Any], story: List[Any], styles: StyleSheet1, level: int) -> None:
    text = element.get("text", "")
    style = styles.get(f"Header{level}", styles["Header1"]) if 1 <= level <= 3 else styles["Header1"]
    story.append(Paragraph(text, style))


def render_paragraph(element: Dict[str, Any], story: List[Any], styles: StyleSheet1) -> None:
    style = resolve_paragraph_style(styles, element.get("style"))
    text = element.get("text", "")
    story.append(Paragraph(text, style))


def render_spacer(element: Dict[str, Any], story: List[Any]) -> None:
    height = float(element.get("height", 12))
    story.append(Spacer(1, height))


def render_page_break(story: List[Any]) -> None:
    story.append(PageBreak())


def resolve_image_path(base_dir: Path, path_value: str) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def render_image(element: Dict[str, Any], story: List[Any], base_dir: Path, styles: StyleSheet1, temp_files: List[Path]) -> None:
    # Verificar si es imagen desde Supabase
    supabase_config = element.get("supabase")
    if supabase_config:
        if download_image_from_supabase:
            img_path = download_image_from_supabase(supabase_config)
            if img_path:
                temp_files.append(img_path)  # Agregar a lista para limpieza posterior
            else:
                logging.warning("No se pudo descargar imagen desde Supabase. Se omite.")
                return
        else:
            logging.warning("Función download_image_from_supabase no disponible. Se omite.")
            return
    else:
        # Imagen local tradicional
        path_value = element.get("path")
        if not path_value:
            logging.warning("Elemento 'image' sin 'path' ni 'supabase'. Se omite.")
            return
            
        img_path = resolve_image_path(base_dir, path_value)
        
        # Si no existe localmente, intentar descargar desde Supabase automáticamente
        if not img_path.exists():
            logging.info("Imagen no encontrada localmente: %s. Intentando descargar desde Supabase...", path_value)
            try:
                if create_image_config and download_image_from_supabase:
                    # Crear configuración automática para Supabase
                    supabase_config = create_image_config(path_value)
                    downloaded_path = download_image_from_supabase(supabase_config)
                    if downloaded_path and downloaded_path.exists():
                        img_path = downloaded_path
                        temp_files.append(img_path)  # Agregar a lista para limpieza posterior
                        logging.info("Imagen descargada exitosamente desde Supabase: %s", path_value)
                    else:
                        logging.warning("No se pudo descargar imagen desde Supabase: %s. Se omite.", path_value)
                        return
                else:
                    logging.warning("Funciones de Supabase no disponibles. Imagen %s omitida.", path_value)
                    return
            except Exception as e:
                logging.warning("Error descargando imagen desde Supabase %s: %s. Se omite.", path_value, e)
                return

    width = to_inches(element.get("width"))
    height = to_inches(element.get("height"))

    img = Image(str(img_path), width=width, height=height) if (width or height) else Image(str(img_path))
    story.append(img)
    caption = element.get("caption")
    if caption:
        story.append(Spacer(1, 6))
        story.append(Paragraph(caption, styles["Caption"]))


def render_table(element: Dict[str, Any], story: List[Any]) -> None:
    headers = element.get("headers", [])
    rows = element.get("rows", [])
    data = [headers] + rows if headers else rows
    if not data:
        return

    table = Table(data, hAlign="LEFT")
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ]
    )
    table.setStyle(style)
    story.append(table)


def render_list(element: Dict[str, Any], story: List[Any], styles: StyleSheet1) -> None:
    items = element.get("items", [])
    if not items:
        return
    lf_items = [ListItem(Paragraph(str(text), styles["Body"])) for text in items]
    story.append(ListFlowable(lf_items, bulletType="bullet", start="\u2022", leftIndent=12))


def render_key_value_list(element: Dict[str, Any], story: List[Any], styles: StyleSheet1) -> None:
    items = element.get("items", [])
    if not items:
        return
    data: List[List[Any]] = []
    for kv in items:
        key = Paragraph(f"<b>{kv.get('key', '')}:</b>", styles["Body"])
        val = Paragraph(str(kv.get("value", "")), styles["Body"])
        data.append([key, val])
    table = Table(data, colWidths=[2.5 * inch, None], hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    story.append(table)


# Función eliminada - ya no se generan gráficos


def build_story(content: List[Dict[str, Any]], styles: StyleSheet1, base_dir: Path) -> Tuple[List[Any], List[Path]]:
    story: List[Any] = []
    temp_files: List[Path] = []
    
    for element in content:
        etype = element.get("type")
        if etype == "header1":
            render_header(element, story, styles, 1)
        elif etype == "header2":
            render_header(element, story, styles, 2)
        elif etype == "header3":
            render_header(element, story, styles, 3)
        elif etype == "paragraph":
            render_paragraph(element, story, styles)
        elif etype == "spacer":
            render_spacer(element, story)
        elif etype == "page_break":
            render_page_break(story)
        elif etype == "image":
            render_image(element, story, base_dir, styles, temp_files)
        elif etype == "table":
            render_table(element, story)
        elif etype == "list":
            render_list(element, story, styles)
        elif etype == "key_value_list":
            render_key_value_list(element, story, styles)
        else:
            logging.warning("Tipo de elemento no soportado: %s", etype)
    
    return story, temp_files


def get_json_structure(
    json_path: Optional[Path] = None,
    auto_download: bool = True,
    json_filename: str = "estructura_informe.json"
) -> Tuple[Path, bool]:
    """
    Obtiene el archivo JSON de estructura, descargándolo desde Supabase si está habilitado.
    
    Args:
        json_path: Ruta local específica al JSON (opcional)
        auto_download: Si debe intentar descargar desde Supabase primero
        json_filename: Nombre del archivo JSON en Supabase
        
    Returns:
        Tuple[Path, bool]: (ruta_al_json, es_temporal)
    """
    # Si se especifica una ruta local y existe, usarla directamente
    if json_path and json_path.exists():
        logging.info(f"📄 Usando archivo JSON local: {json_path}")
        return json_path, False
    
    # Intentar descargar desde Supabase si está habilitado
    if auto_download and download_json_structure_from_supabase:
        try:
            # Construir fallback local
            local_fallback = json_path or Path(json_filename)
            
            logging.info("🌐 Intentando descargar JSON desde Supabase...")
            json_temp_path = download_json_structure_from_supabase(
                json_filename=json_filename,
                local_fallback_path=str(local_fallback) if local_fallback.exists() else None
            )
            
            return json_temp_path, True
            
        except Exception as e:
            logging.warning(f"⚠️ No se pudo descargar JSON desde Supabase: {e}")
    
    # Fallback: usar archivo local
    local_path = json_path or Path(json_filename)
    if local_path.exists():
        logging.info(f"📄 Usando archivo JSON local como fallback: {local_path}")
        return local_path, False
    
    raise FileNotFoundError(f"No se encontró archivo JSON en '{local_path}' ni se pudo descargar desde Supabase")


def build_pdf_from_json(
    json_path: Path, 
    schema_path: Optional[Path] = None, 
    output_path: Optional[Path] = None,
    upload_to_supabase: bool = True
) -> Tuple[Path, Optional[Dict[str, Any]]]:
    """
    Genera un PDF desde JSON y opcionalmente lo sube a Supabase.
    
    Args:
        json_path: Ruta al archivo JSON (puede ser None para auto-descarga)
        schema_path: Ruta al schema de validación
        output_path: Ruta de salida (opcional, se usa temporal si upload_to_supabase=True)
        upload_to_supabase: Si debe subir automáticamente a Supabase
        
    Returns:
        Tuple[Path, Optional[Dict]]: (ruta_pdf_local, info_subida_supabase)
    """
    # Obtener el JSON (desde Supabase o local)
    actual_json_path, is_temp_json = get_json_structure(json_path, auto_download=True)
    
    # Determinar archivo de salida (temporal si se va a subir a Supabase)
    if upload_to_supabase and upload_pdf_to_supabase:
        # Crear archivo temporal para el PDF
        temp_pdf = tempfile.NamedTemporaryFile(
            mode='w+b', 
            suffix='.pdf', 
            prefix='tmp_report_', 
            delete=False
        )
        temp_pdf.close()
        output_file = Path(temp_pdf.name)
        logging.info("📄 Generando PDF temporal para subida a Supabase: %s", output_file)
    else:
        # Usar archivo local como antes
        data_preview = load_json(actual_json_path)  # Carga previa para obtener metadata
        base_dir = actual_json_path.parent
        output_file = output_path or base_dir / data_preview.get("fileName", "informe.pdf")
        logging.info("📄 Generando PDF local: %s", output_file)
    
    upload_info = None
    
    try:
        data = load_json(actual_json_path)
        validate_json(data, schema_path)

        doc_meta = data.get("document", {})
        page_size = A4
        left_margin = right_margin = 36
        top_margin = bottom_margin = 36

        doc = SimpleDocTemplate(
            str(output_file),
            pagesize=page_size,
            title=doc_meta.get("title", "Informe"),
            author=doc_meta.get("author", ""),
            subject=doc_meta.get("subject", ""),
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=top_margin,
            bottomMargin=bottom_margin,
        )

        styles = build_styles()
        story, temp_files = build_story(data.get("content", []), styles, actual_json_path.parent)

        try:
            logging.info("🔨 Construyendo PDF...")
            doc.build(story, canvasmaker=NumberedCanvas)
            
            # Obtener estadísticas del PDF
            pdf_size = output_file.stat().st_size
            pdf_size_mb = pdf_size / (1024 * 1024)
            logging.info("✅ PDF generado: %s (%s bytes, %.2f MB)", output_file, pdf_size, pdf_size_mb)
            
            # Subir a Supabase si está habilitado
            if upload_to_supabase and upload_pdf_to_supabase:
                try:
                    # Usar nombre fijo simple
                    remote_filename = "Reporte.pdf"
                    
                    logging.info("📤 Subiendo PDF a Supabase...")
                    upload_info = upload_pdf_to_supabase(
                        local_pdf_path=output_file,
                        remote_filename=remote_filename,
                        remote_folder="Informes"
                    )
                    
                    logging.info("🌐 PDF subido exitosamente a Supabase: %s", upload_info["remote_path"])
                    
                except Exception as e:
                    logging.error("❌ Error subiendo PDF a Supabase: %s", e)
                    upload_info = {"success": False, "error": str(e)}
            
        finally:
            # Limpiar archivos temporales descargados de Supabase (imágenes)
            if temp_files and cleanup_temp_files:
                cleanup_temp_files(temp_files)
                logging.info("🧹 Limpiados %d archivos temporales de imágenes", len(temp_files))
            elif temp_files:
                # Fallback manual si cleanup_temp_files no está disponible
                for temp_file in temp_files:
                    try:
                        if temp_file.exists():
                            temp_file.unlink()
                            logging.debug("Archivo temporal eliminado: %s", temp_file)
                    except Exception as e:
                        logging.warning("No se pudo eliminar archivo temporal %s: %s", temp_file, e)
                logging.info("🧹 Limpiados %d archivos temporales de imágenes (fallback)", len(temp_files))
    
    finally:
        # Limpiar JSON temporal si fue descargado desde Supabase
        if is_temp_json:
            try:
                if actual_json_path.exists():
                    actual_json_path.unlink()
                    logging.info("📄 JSON temporal eliminado: %s", actual_json_path)
            except Exception as e:
                logging.warning("No se pudo eliminar JSON temporal %s: %s", actual_json_path, e)
        
        # Limpiar PDF temporal si se subió exitosamente a Supabase
        if upload_to_supabase and upload_info and upload_info.get("success") and output_file.exists():
            try:
                output_file.unlink()
                logging.info("📄 PDF temporal eliminado tras subida exitosa: %s", output_file)
                # Devolver una ruta de referencia para el PDF en Supabase
                if upload_info:
                    supabase_reference = Path(f"supabase://{upload_info['remote_path']}")
                    return supabase_reference, upload_info
            except Exception as e:
                logging.warning("No se pudo eliminar PDF temporal %s: %s", output_file, e)
    
    return output_file, upload_info


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generador de informes PDF basado en JSON")
    parser.add_argument(
        "--json", 
        dest="json_path", 
        required=False, 
        help="Ruta al archivo JSON de entrada (si no se especifica, se descarga desde Supabase)"
    )
    parser.add_argument(
        "--schema",
        dest="schema_path",
        default=str(Path("schema") / "report_schema.json"),
        help="Ruta al archivo JSON Schema para validar la entrada",
    )
    parser.add_argument("--output", dest="output", default=None, help="Ruta de salida opcional del PDF")
    parser.add_argument(
        "--log-level",
        dest="log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivel de logging",
    )
    parser.add_argument(
        "--no-download",
        dest="no_download",
        action="store_true",
        help="Deshabilitar descarga automática desde Supabase (usar solo archivos locales)"
    )
    parser.add_argument(
        "--no-upload",
        dest="no_upload",
        action="store_true",
        help="Deshabilitar subida automática a Supabase (guardar solo local)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    
    # Determinar ruta del JSON
    if args.json_path:
        json_path = Path(args.json_path).resolve()
        if not json_path.exists() and args.no_download:
            raise FileNotFoundError(f"No existe el archivo JSON: {json_path}")
    else:
        # Modo automático: usar archivo por defecto o descargar desde Supabase
        json_path = Path("estructura_informe.json")
        if args.no_download and not json_path.exists():
            raise FileNotFoundError(f"No existe el archivo JSON por defecto: {json_path} (descarga deshabilitada)")

    schema_path = Path(args.schema_path).resolve() if args.schema_path else None
    output_path = Path(args.output).resolve() if args.output else None
    
    # Determinar si se debe subir a Supabase (por defecto SÍ, a menos que se use --no-upload)
    upload_to_supabase = not args.no_upload

    # Generar PDF
    pdf_path, upload_info = build_pdf_from_json(
        json_path=json_path, 
        schema_path=schema_path, 
        output_path=output_path,
        upload_to_supabase=upload_to_supabase
    )
    
    # Mostrar resultados
    if upload_to_supabase and upload_info and upload_info.get("success"):
        print("PDF subido exitosamente a Supabase:")
        print(f"   Ubicación: {upload_info['remote_path']}")
        print(f"   Tamaño: {upload_info['file_size_mb']} MB")
        if upload_info.get("public_url"):
            print(f"   URL: {upload_info['public_url']}")
    else:
        print(f"PDF generado localmente: {pdf_path}")
        if pdf_path.exists():
            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            print(f"   Tamaño: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()


