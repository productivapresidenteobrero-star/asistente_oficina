import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from backend.database import get_db

logger = logging.getLogger("consultas")
router = APIRouter(prefix="/api/consultas", tags=["consultas"])

# ── Schemas ───────────────────────────────────────────────────────────────────

class ConsultaCreate(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    fecha_inicio: str   # YYYY-MM-DD
    fecha_cierre: str   # YYYY-MM-DD

class PreguntaCreate(BaseModel):
    texto: str
    tipo: str = "si_no"          # si_no | multiple | texto
    opciones: Optional[List[str]] = []

class RespuestaCreate(BaseModel):
    pregunta_id: int
    participante: Optional[str] = None
    respuesta: str

# ── Consultas ─────────────────────────────────────────────────────────────────

@router.get("/")
async def listar_consultas():
    """Lista todas las consultas populares."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM consultas_populares ORDER BY fecha_inicio DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

@router.post("/")
async def crear_consulta(data: ConsultaCreate):
    """Crea una nueva consulta popular."""
    async with await get_db() as db:
        cursor = await db.execute(
            """INSERT INTO consultas_populares (titulo, descripcion, fecha_inicio, fecha_cierre)
               VALUES (?, ?, ?, ?)""",
            (data.titulo, data.descripcion, data.fecha_inicio, data.fecha_cierre)
        )
        await db.commit()
        return {"id": cursor.lastrowid, "mensaje": "Consulta creada exitosamente"}

@router.get("/{consulta_id}")
async def obtener_consulta(consulta_id: int):
    """Obtiene una consulta con sus preguntas."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM consultas_populares WHERE id=?", (consulta_id,)
        )
        consulta = await cursor.fetchone()
        if not consulta:
            raise HTTPException(status_code=404, detail="Consulta no encontrada")
        
        cursor = await db.execute(
            "SELECT * FROM preguntas_consulta WHERE consulta_id=?", (consulta_id,)
        )
        preguntas = await cursor.fetchall()
        
        result = dict(consulta)
        result["preguntas"] = [dict(p) for p in preguntas]
        return result

@router.put("/{consulta_id}/cerrar")
async def cerrar_consulta(consulta_id: int):
    """Cierra una consulta activa."""
    async with await get_db() as db:
        await db.execute(
            "UPDATE consultas_populares SET estado='cerrada' WHERE id=?", (consulta_id,)
        )
        await db.commit()
        return {"mensaje": "Consulta cerrada exitosamente"}

# ── Preguntas ─────────────────────────────────────────────────────────────────

@router.post("/{consulta_id}/preguntas")
async def agregar_pregunta(consulta_id: int, data: PreguntaCreate):
    """Agrega una pregunta a una consulta."""
    import json
    async with await get_db() as db:
        cursor = await db.execute(
            """INSERT INTO preguntas_consulta (consulta_id, texto, tipo, opciones)
               VALUES (?, ?, ?, ?)""",
            (consulta_id, data.texto, data.tipo, json.dumps(data.opciones or []))
        )
        await db.commit()
        return {"id": cursor.lastrowid, "mensaje": "Pregunta agregada exitosamente"}

# ── Respuestas ────────────────────────────────────────────────────────────────

@router.post("/responder")
async def registrar_respuesta(data: RespuestaCreate):
    """Registra una respuesta a una pregunta de consulta."""
    async with await get_db() as db:
        cursor = await db.execute(
            """INSERT INTO respuestas_consulta (pregunta_id, participante, respuesta)
               VALUES (?, ?, ?)""",
            (data.pregunta_id, data.participante, data.respuesta)
        )
        await db.commit()
        return {"id": cursor.lastrowid, "mensaje": "Respuesta registrada exitosamente"}

# ── Resultados ────────────────────────────────────────────────────────────────

@router.get("/{consulta_id}/resultados")
async def resultados_consulta(consulta_id: int):
    """Calcula los resultados agregados de una consulta."""
    async with await get_db() as db:
        # Obtener preguntas de esta consulta
        cursor = await db.execute(
            "SELECT * FROM preguntas_consulta WHERE consulta_id=?", (consulta_id,)
        )
        preguntas = await cursor.fetchall()
        
        resultados = []
        for pregunta in preguntas:
            pid = pregunta["id"]
            
            # Contar total de respuestas
            c_total = await db.execute(
                "SELECT COUNT(*) FROM respuestas_consulta WHERE pregunta_id=?", (pid,)
            )
            total = (await c_total.fetchone())[0]
            
            # Agrupar respuestas
            c_agrupado = await db.execute(
                """SELECT respuesta, COUNT(*) as cantidad 
                   FROM respuestas_consulta 
                   WHERE pregunta_id=? 
                   GROUP BY respuesta 
                   ORDER BY cantidad DESC""",
                (pid,)
            )
            agrupado = await c_agrupado.fetchall()
            
            desglose = []
            for row in agrupado:
                pct = round((row["cantidad"] / total * 100), 1) if total > 0 else 0
                desglose.append({
                    "respuesta": row["respuesta"],
                    "cantidad": row["cantidad"],
                    "porcentaje": pct
                })
            
            resultados.append({
                "pregunta_id": pid,
                "pregunta_texto": pregunta["texto"],
                "tipo": pregunta["tipo"],
                "total_respuestas": total,
                "desglose": desglose
            })
        
        return {
            "consulta_id": consulta_id,
            "resultados": resultados,
            "generado_en": datetime.now().isoformat()
        }
