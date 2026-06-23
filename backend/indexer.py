import os
import hashlib
import json
import logging
import asyncio
from pathlib import Path
import fitz  # PyMuPDF
import docx
import pandas as pd
from PIL import Image
import pytesseract
from backend.config import DOCUMENTOS_PATH, CHROMA_PATH, IDIOMA, TESSERACT_LANG, COHERE_API_KEY, GEMINI_API_KEY
from backend.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indexer")

# Intentar inicializar LanceDB
db = None
collection = None
try:
    import lancedb
    from lancedb.pydantic import Vector, LanceModel
    from lancedb.embeddings import get_registry

    # Usamos la API de Cohere (embed-multilingual-v3.0) para embeddings rápidos en la nube, sin procesar en la CPU local.
    # Alternativamente, si no está configurada, se puede usar "gemini" o "openai" mediante el registro.
    # Como la clave de Cohere se lee del archivo .env y se exporta a las variables del sistema, LanceDB la detectará automáticamente.
    if COHERE_API_KEY and COHERE_API_KEY != "tu_clave_cohere_aqui":
        os.environ["COHERE_API_KEY"] = COHERE_API_KEY
        embed_fn = get_registry().get("cohere").create(name="embed-multilingual-v3.0")
        logger.info("Usando Cohere API para embeddings (embed-multilingual-v3.0).")
    else:
        embed_fn = get_registry().get("sentence-transformers").create(name="paraphrase-multilingual-MiniLM-L12-v2")
        logger.info("Usando sentence-transformers local (paraphrase-multilingual-MiniLM-L12-v2).")

    class Documento(LanceModel):
        id: str
        ruta: str
        nombre: str
        pagina: str
        tipo: str
        texto: str = embed_fn.SourceField()
        vector: Vector(embed_fn.ndims()) = embed_fn.VectorField()

    db = lancedb.connect(CHROMA_PATH + "_lancedb")
    collection = db.create_table("documentos_comuna", schema=Documento, exist_ok=True)
    logger.info("LanceDB y modelo de embeddings inicializados exitosamente.")
except ImportError:
    logger.warning("LanceDB no instalado o sentence-transformers ausente. Se usará FTS5 como fallback.")
except Exception as e:
    logger.error(f"Error al inicializar LanceDB/Embeddings: {e}. Se usará FTS5 como fallback.")

# Asegurar que el directorio de documentos existe
DOCUMENTOS_PATH.mkdir(parents=True, exist_ok=True)

def calcular_hash_archivo(filepath: Path) -> str:
    """Calcula el hash SHA-256 de un archivo para detectar cambios."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def extraer_texto_pdf(filepath: Path) -> list:
    """Extrae texto de un archivo PDF por páginas."""
    paginas = []
    try:
        doc = fitz.open(filepath)
        for i, pagina in enumerate(doc):
            texto = pagina.get_text()
            if texto.strip():
                paginas.append({"pagina": i + 1, "texto": texto.strip()})
            else:
                # Si la página está vacía (puede ser escaneada), intentar OCR en la página
                try:
                    pix = pagina.get_pixmap()
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    texto_ocr = pytesseract.image_to_string(img, lang=TESSERACT_LANG)
                    if texto_ocr.strip():
                        paginas.append({"pagina": i + 1, "texto": f"[OCR] {texto_ocr.strip()}"})
                except Exception as ocr_err:
                    logger.warning(f"No se pudo hacer OCR en página {i+1} de {filepath.name}: {ocr_err}")
        doc.close()
    except Exception as e:
        logger.error(f"Error al leer PDF {filepath.name}: {e}")
    return paginas

def extraer_texto_docx(filepath: Path) -> list:
    """Extrae texto de un archivo Word (.docx)."""
    try:
        doc = docx.Document(filepath)
        texto_completo = []
        for para in doc.paragraphs:
            if para.text.strip():
                texto_completo.append(para.text.strip())
        
        # Agrupar en pseudo-páginas o chunks
        texto = "\n".join(texto_completo)
        if texto:
            return [{"pagina": 1, "texto": texto}]
    except Exception as e:
        logger.error(f"Error al leer DOCX {filepath.name}: {e}")
    return []

def extraer_texto_excel(filepath: Path) -> list:
    """Extrae texto estructurado de un archivo Excel (.xlsx, .xls)."""
    try:
        xls = pd.ExcelFile(filepath)
        hojas = []
        for nombre_hoja in xls.sheet_names:
            df = pd.read_excel(filepath, sheet_name=nombre_hoja)
            # Convertir dataframe a formato string legible
            txt = df.to_string(index=False)
            if txt.strip():
                hojas.append({"pagina": nombre_hoja, "texto": f"Hoja: {nombre_hoja}\n{txt}"})
        return hojas
    except Exception as e:
        logger.error(f"Error al leer Excel {filepath.name}: {e}")
    return []

def extraer_texto_imagen(filepath: Path) -> list:
    """Extrae texto de una imagen usando OCR."""
    try:
        img = Image.open(filepath)
        texto = pytesseract.image_to_string(img, lang=TESSERACT_LANG)
        if texto.strip():
            return [{"pagina": 1, "texto": texto.strip()}]
    except Exception as e:
        logger.error(f"Error al leer Imagen {filepath.name}: {e}")
    return []

def extraer_texto_txt(filepath: Path) -> list:
    """Extrae texto de un archivo de texto simple."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            texto = f.read()
            if texto.strip():
                return [{"pagina": 1, "texto": texto.strip()}]
    except Exception as e:
        logger.error(f"Error al leer TXT {filepath.name}: {e}")
    return []

def chunk_texto(texto: str, max_chars: int = 1000, overlap: int = 150) -> list:
    """Divide un texto largo en trozos (chunks) con solapamiento."""
    chunks = []
    start = 0
    while start < len(texto):
        end = start + max_chars
        chunks.append(texto[start:end])
        start += max_chars - overlap
    return chunks

async def registrar_documento_db(nombre: str, ruta: str, tipo: str, hash_arch: str):
    """Registra el archivo en la base de datos SQLite."""
    async with await get_db() as db:
        # También creamos tabla FTS5 si no existe para la búsqueda de texto clásica
        await db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_documentos USING fts5(
            documento_id,
            nombre,
            ruta,
            pagina,
            contenido
        );
        """)
        
        await db.execute(
            "INSERT OR REPLACE INTO documentos (nombre, ruta, tipo_documento, hash_archivo) VALUES (?, ?, ?, ?)",
            (nombre, ruta, tipo, hash_arch)
        )
        await db.commit()

async def insertar_chunks_fts(ruta: str, nombre: str, chunks_paginas: list):
    """Inserta los trozos de texto en la tabla FTS5 de SQLite."""
    async with await get_db() as db:
        # Obtener el ID del documento
        cursor = await db.execute("SELECT id FROM documentos WHERE ruta = ?", (ruta,))
        row = await cursor.fetchone()
        if not row:
            return
        doc_id = row[0]
        
        # Limpiar chunks anteriores de este documento
        await db.execute("DELETE FROM fts_documentos WHERE documento_id = ?", (str(doc_id),))
        
        # Insertar nuevos chunks
        for item in chunks_paginas:
            pag = str(item["pagina"])
            texto = item["texto"]
            
            # Dividir en chunks para indexación más granular
            chunks = chunk_texto(texto)
            for chunk in chunks:
                await db.execute(
                    "INSERT INTO fts_documentos (documento_id, nombre, ruta, pagina, contenido) VALUES (?, ?, ?, ?, ?)",
                    (str(doc_id), nombre, ruta, pag, chunk)
                )
        await db.commit()

async def indexar_archivo(filepath: Path):
    """Procesa un archivo individual y lo indexa en ChromaDB y FTS5."""
    ext = filepath.suffix.lower()
    nombre = filepath.name
    ruta = str(filepath.resolve())
    
    hash_actual = await asyncio.to_thread(calcular_hash_archivo, filepath)
    
    # Verificar si el archivo ya fue indexado y no ha cambiado
    async with await get_db() as db:
        cursor = await db.execute("SELECT hash_archivo FROM documentos WHERE ruta = ?", (ruta,))
        row = await cursor.fetchone()
        if row and row[0] == hash_actual:
            logger.info(f"El archivo {nombre} no ha cambiado. Se omite indexación.")
            return

    logger.info(f"Indexando archivo: {nombre}")
    
    # Extraer el texto según el tipo
    paginas = []
    tipo = "TXT"
    if ext == ".pdf":
        paginas = await asyncio.to_thread(extraer_texto_pdf, filepath)
        tipo = "PDF"
    elif ext in [".docx", ".doc"]:
        paginas = await asyncio.to_thread(extraer_texto_docx, filepath)
        tipo = "DOCX"
    elif ext in [".xlsx", ".xls", ".csv"]:
        paginas = await asyncio.to_thread(extraer_texto_excel, filepath)
        tipo = "XLSX"
    elif ext in [".png", ".jpg", ".jpeg", ".bmp"]:
        paginas = await asyncio.to_thread(extraer_texto_imagen, filepath)
        tipo = "IMG"
    elif ext in [".txt", ".md"]:
        paginas = await asyncio.to_thread(extraer_texto_txt, filepath)
        tipo = "TXT"
    else:
        logger.warning(f"Tipo de archivo no soportado: {ext}")
        return
        
    if not paginas:
        logger.warning(f"No se pudo extraer texto del archivo: {nombre}")
        return

    # Registrar en base de datos SQLite
    await registrar_documento_db(nombre, ruta, tipo, hash_actual)
    
    # Indexar en SQLite FTS5 (búsqueda clásica)
    await insertar_chunks_fts(ruta, nombre, paginas)
    
    # Indexar en LanceDB (búsqueda semántica) si está disponible
    if collection is not None:
        try:
            # Eliminar documentos viejos en LanceDB si existen
            clean_ruta = str(ruta).replace("'", "''")
            await asyncio.to_thread(collection.delete, f"ruta = '{clean_ruta}'")
            
            data = []
            
            for item in paginas:
                pag = item["pagina"]
                texto = item["texto"]
                
                chunks = chunk_texto(texto)
                for idx, chunk in enumerate(chunks):
                    chunk_id = f"{ruta}_p{pag}_c{idx}"
                    data.append({
                        "id": chunk_id,
                        "ruta": ruta,
                        "nombre": nombre,
                        "pagina": str(pag),
                        "tipo": tipo,
                        "texto": chunk
                    })
            
            if data:
                await asyncio.to_thread(collection.add, data)
                logger.info(f"Éxito al indexar en LanceDB: {nombre} ({len(data)} chunks)")
        except Exception as e:
            logger.error(f"Error al indexar en LanceDB para {nombre}: {e}")

async def indexar_todos_documentos():
    """Escanea la carpeta de documentos de la comuna e indexa todos los archivos nuevos/modificados."""
    # Tipos de archivo válidos
    extensiones_validas = {
        '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv', 
        '.png', '.jpg', '.jpeg', '.bmp', '.txt', '.md'
    }

    # Carpetas a ignorar para evitar indexar paquetes de Python, git, cache, etc.
    DIRS_EXCLUIDOS = {
        'venv', '.venv', 'env', '__pycache__', '.git', '.idea',
        'node_modules', 'site-packages', 'dist-packages',
        'dist', 'build', '.mypy_cache', '.pytest_cache', 'chroma_db',
    }

    if not DOCUMENTOS_PATH.exists():
        logger.warning(f"La ruta de documentos {DOCUMENTOS_PATH} no existe.")
        return
        
    encontrados = 0
    for root, dirs, files in os.walk(DOCUMENTOS_PATH, topdown=True):
        # Podar directorios excluidos in-place para que os.walk no descienda en ellos
        dirs[:] = [d for d in dirs if d not in DIRS_EXCLUIDOS and not d.startswith('.')]

        for file in files:
            if file.startswith("~$"):
                continue  # Ignorar archivos temporales de Office
            filepath = Path(root) / file
            if filepath.suffix.lower() in extensiones_validas:
                encontrados += 1
                try:
                    await indexar_archivo(filepath)
                except Exception as e:
                    logger.error(f"Error procesando {file}: {e}")
                    
    logger.info(f"Indexación completada. Total de archivos procesados: {encontrados}")
