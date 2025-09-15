## Generador de Informes PDF basado en JSON

Este proyecto genera PDFs de forma declarativa a partir de un archivo JSON. La lógica de negocio (qué va en el informe) se define en el JSON; la lógica de presentación (cómo se renderiza) la implementa el script con ReportLab. **Las imágenes se descargan automáticamente desde Supabase Storage.**

### Requisitos
- Python 3.10+
- Windows, macOS o Linux
- Cuenta de Supabase con Storage configurado

### Instalación
```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

**Configurar variables de entorno para Supabase:** (usa Service Role si el bucket es privado)
```bash
# Windows PowerShell
$Env:SUPABASE_URL = "https://TU_PROYECTO.supabase.co"
$Env:SUPABASE_SERVICE_ROLE_KEY = "TU_SERVICE_ROLE"
# (opcional) si tu bucket es público, puedes usar la anon key:
# $Env:SUPABASE_KEY = "TU_ANON_KEY"
# macOS/Linux
export SUPABASE_URL="https://TU_PROYECTO.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="TU_SERVICE_ROLE"
# (opcional) si tu bucket es público, puedes usar la anon key:
# export SUPABASE_KEY="TU_ANON_KEY"
```

### Uso
Generar un PDF a partir de un JSON existente:
```bash
python pdf_generator.py --json estructura_informe.json
```

Validar contra el esquema:
```bash
python pdf_generator.py --json estructura_informe.json --schema schema/report_schema.json
```

Especificar una ruta de salida:
```bash
python pdf_generator.py --json estructura_informe.json --output salida.pdf
```

### Estructura JSON
- `fileName`: nombre del PDF de salida si no se usa `--output`.
- `document`: metadatos (`title`, `author`, `subject`).
- `content`: arreglo de bloques en orden. Tipos soportados:
  - `header1`, `header2`, `header3` (props: `text`)
  - `paragraph` (props: `text`, `style` = `body|italic|bold|centered|disclaimer`)
  - `spacer` (props: `height` en puntos)
  - `page_break`
  - `image` (props: `path` para locales O `supabase` para Supabase Storage)
  - `table` (props: `headers?`, `rows`)
  - `list` (props: `items`)
  - `key_value_list` (props: `items: [{key, value}]`)

### Imágenes desde Supabase Storage

#### Imagen pública:
```json
{
  "type": "image",
  "supabase": {
    "bucket": "reports",
    "path": "charts/portfolio_growth.png",
    "public": true,
    "use_url": false
  },
  "width": 6,
  "height": 3.2,
  "caption": "Gráfico descargado desde Supabase"
}
```

#### Imagen privada (con URL firmada):
```json
{
  "type": "image",
  "supabase": {
    "bucket": "private-reports",
    "path": "sensitive/analysis.png",
    "public": false,
    "expires_in": 3600,
    "use_url": true
  },
  "width": 6,
  "height": 3.2,
  "caption": "Imagen privada con expiración en 1 hora"
}
```

#### Transformaciones de imagen (Storage Image Transform):
```json
{
  "type": "image",
  "supabase": {
    "bucket": "reports",
    "path": "charts/portfolio_growth.png",
    "public": true,
    "transform": { "width": 1200, "height": 800, "quality": 80, "resize": "cover", "format": "origin" }
  },
  "width": 6,
  "height": 3.2,
  "caption": "Imagen transformada desde Supabase"
}
```

#### Imagen local (tradicional):
```json
{
  "type": "image",
  "path": "local_image.png",
  "width": 6,
  "height": 3.2,
  "caption": "Imagen local"
}
```

### Ejemplo completo
Usa el archivo `estructura_informe.json` como referencia de estructura real:
```bash
python pdf_generator.py --json estructura_informe.json
```

Este archivo contiene un ejemplo real de informe estratégico de portafolio con todos los elementos soportados.

### Notas importantes
- **Las imágenes desde Supabase se descargan automáticamente** y se limpian después de generar el PDF.
- Las rutas de `image.path` se resuelven relativas al JSON para imágenes locales.
- Si una imagen no existe o falla la descarga, se omite con un aviso en los logs.
- El esquema JSON está en `schema/report_schema.json`.
- **Para buckets privados**, asegúrate de que tu API key tenga permisos de lectura en Storage.


