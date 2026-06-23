import logging
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from backend.database import get_db
from backend.pdf_extractor import extraer_datos_acta

logger = logging.getLogger("actas")
router = APIRouter(prefix="/api/actas", tags=["actas"])

# Carpeta para guardar PDFs de actas subidas
ACTAS_DIR = Path(__file__).parent.parent / "media" / "actas"
ACTAS_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload")
async def upload_acta(file: UploadFile = File(...)):
    """Sube un acta PDF, extrae sus datos y retorna una previsualización."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

    # Guardar PDF
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"acta_{timestamp}_{file.filename}"
    pdf_path = ACTAS_DIR / filename

    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Extraer datos
    try:
        datos = extraer_datos_acta(pdf_path)
    except Exception as e:
        # Limpiar archivo si falla la extracción
        pdf_path.unlink(missing_ok=True)
        logger.error(f"Error extrayendo acta {file.filename}: {e}")
        raise HTTPException(status_code=422, detail=f"No se pudieron extraer datos del PDF: {str(e)}")

    datos["filename"] = file.filename

    async with await get_db() as db:
        # Verificar si ya existe un acta con ese código
        acta_id = None
        ya_existe = False

        if datos["codigo_registro"]:
            cursor = await db.execute(
                "SELECT id FROM actas WHERE codigo_registro = ?",
                (datos["codigo_registro"],)
            )
            existing = await cursor.fetchone()
            if existing:
                acta_id = existing[0]
                ya_existe = True

        if not ya_existe:
            cursor = await db.execute(
                """INSERT INTO actas (codigo_registro, fecha_acta, nombre_consejo, sector, pdf_path)
                   VALUES (?, ?, ?, ?, ?)""",
                (datos["codigo_registro"], datos["fecha_acta"],
                 datos["nombre_consejo"], datos["sector"], str(pdf_path))
            )
            await db.commit()
            acta_id = cursor.lastrowid

    datos["ya_existe"] = ya_existe
    datos["acta_id"] = acta_id

    return {"status": "ok", "datos": datos}

@router.post("/{acta_id}/save")
async def save_acta(acta_id: int):
    """Guarda los datos de un acta extraída en la base de datos (consejo + voceros)."""
    # Primero obtener los datos del acta desde el archivo PDF guardado
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM actas WHERE id = ?", (acta_id,))
        acta = await cursor.fetchone()

    if not acta:
        raise HTTPException(status_code=404, detail="Acta no encontrada en BD")

    # Re-extraer datos del PDF por seguridad
    pdf_path = acta["pdf_path"]
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="Archivo PDF del acta no encontrado")

    datos = extraer_datos_acta(pdf_path)

    async with await get_db() as db:
        # Buscar o crear consejo comunal
        cursor = await db.execute(
            "SELECT id FROM consejos_comunales WHERE nombre = ?",
            (datos["nombre_consejo"],)
        )
        consejo = await cursor.fetchone()

        if consejo:
            consejo_id = consejo[0]
            # Actualizar datos del consejo
            await db.execute(
                "UPDATE consejos_comunales SET sector = ? WHERE id = ?",
                (datos["sector"], consejo_id)
            )
        else:
            # Crear nuevo consejo
            cursor = await db.execute(
                "INSERT INTO consejos_comunales (nombre, sector, fecha_constitucion) VALUES (?, ?, ?)",
                (datos["nombre_consejo"], datos["sector"], datos["fecha_acta"])
            )
            consejo_id = cursor.lastrowid

        # Actualizar el acta (ya existe de la etapa de upload)
        await db.execute(
            "UPDATE actas SET codigo_registro=?, fecha_acta=?, consejo_id=?, nombre_consejo=?, sector=? WHERE id=?",
            (datos["codigo_registro"], datos["fecha_acta"], consejo_id,
             datos["nombre_consejo"], datos["sector"], acta_id)
        )

        # Guardar voceros
        insertados = 0
        actualizados = 0
        for v in datos["voceros"]:
            cedula_limpia = v.get("cedula", "").strip()
            try:
                votos = int(v.get("votos", 0) or 0)

                existing_vocero = None
                if cedula_limpia:
                    cursor = await db.execute(
                        "SELECT id FROM voceros WHERE cedula = ? AND consejo_id = ?",
                        (cedula_limpia, consejo_id)
                    )
                    existing_vocero = await cursor.fetchone()

                if existing_vocero:
                    await db.execute(
                        """UPDATE voceros SET consejo_id=?, nombre=?, cargo=?, tipo=?, telefono=?, votos=?, acta_id=?, activo=1
                           WHERE id=?""",
                        (consejo_id, v["nombre"], v["voceria"], v["tipo"], v.get("telefono", ""), votos, acta_id, existing_vocero[0])
                    )
                    actualizados += 1
                else:
                    await db.execute(
                        """INSERT INTO voceros (consejo_id, nombre, cedula, cargo, tipo, telefono, votos, acta_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (consejo_id, v["nombre"], cedula_limpia, v["voceria"], v["tipo"], v.get("telefono", ""), votos, acta_id)
                    )
                    insertados += 1
            except Exception as e:
                logger.warning("Error guardando vocero %s: %s", v.get("nombre"), e)

        await db.commit()

    return {
        "status": "ok",
        "mensaje": f"Acta guardada. {insertados} voceros insertados, {actualizados} actualizados.",
        "acta_id": acta_id,
        "consejo_id": consejo_id
    }

@router.get("")
async def list_actas():
    """Lista todas las actas registradas."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM actas ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

@router.get("/{acta_id}")
async def get_acta(acta_id: int):
    """Obtiene los datos de un acta específica."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM actas WHERE id = ?", (acta_id,))
        acta = await cursor.fetchone()
        if not acta:
            raise HTTPException(status_code=404, detail="Acta no encontrada")

        # Obtener voceros asociados
        cursor = await db.execute(
            "SELECT * FROM voceros WHERE acta_id = ? ORDER BY id", (acta_id,)
        )
        voceros = await cursor.fetchall()

        result = dict(acta)
        result["voceros"] = [dict(v) for v in voceros]
        return result
