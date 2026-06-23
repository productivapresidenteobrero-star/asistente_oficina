import json
import logging
from typing import List, Optional
from datetime import datetime
from backend.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("activities")

async def listar_categorias() -> List[str]:
    """Retorna la lista de todas las categorías disponibles en la BD."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT nombre FROM categorias ORDER BY nombre ASC")
        rows = await cursor.fetchall()
        return [row["nombre"] for row in rows]

async def agregar_categoria(nombre: str) -> bool:
    """Agrega una nueva categoría personalizada a la base de datos."""
    nombre_limpio = nombre.strip()
    if not nombre_limpio:
        return False
    async with await get_db() as db:
        try:
            await db.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre_limpio,))
            await db.commit()
            return True
        except Exception as e:
            logger.warning(f"No se pudo agregar la categoría {nombre_limpio} (probablemente ya existe): {e}")
            return False

async def registrar_actividad(
    fecha: str,
    categoria: str,
    descripcion: str,
    participantes: int = 0,
    fotos: List[str] = None
) -> dict:
    """
    Registra una actividad de la comuna.
    Asegura que la categoría exista agregándola si es nueva.
    """
    if fotos is None:
        fotos = []
        
    # Verificar y asegurar la categoría
    await agregar_categoria(categoria)
    
    # Formatear la fecha
    if not fecha:
        fecha = datetime.now().strftime("%Y-%m-%d")
        
    fotos_json = json.dumps(fotos)
    
    async with await get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO actividades (fecha, categoria, descripcion, participantes, fotos)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fecha, categoria, descripcion, participantes, fotos_json)
        )
        await db.commit()
        actividad_id = cursor.lastrowid
        
    return {
        "id": actividad_id,
        "fecha": fecha,
        "categoria": categoria,
        "descripcion": descripcion,
        "participantes": participantes,
        "fotos": fotos
    }

async def obtener_actividades(
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    categoria: Optional[str] = None
) -> List[dict]:
    """Retorna las actividades de la comuna que cumplen con los filtros seleccionados."""
    query = "SELECT * FROM actividades WHERE 1=1"
    params = []
    
    if fecha_inicio:
        query += " AND fecha >= ?"
        params.append(fecha_inicio)
        
    if fecha_fin:
        query += " AND fecha <= ?"
        params.append(fecha_fin)
        
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
        
    query += " ORDER BY fecha DESC, id DESC"
    
    async with await get_db() as db:
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()
        
        actividades = []
        for row in rows:
            try:
                fotos_lista = json.loads(row["fotos"])
                if isinstance(fotos_lista, str):
                    fotos_lista = json.loads(fotos_lista)
            except Exception:
                fotos_lista = []
                
            actividades.append({
                "id": row["id"],
                "fecha": row["fecha"],
                "categoria": row["categoria"],
                "descripcion": row["descripcion"],
                "participantes": row["participantes"],
                "fotos": fotos_lista,
                "created_at": row["created_at"]
            })
            
        return actividades

async def eliminar_actividad(act_id: int) -> bool:
    """Elimina una actividad por su ID."""
    async with await get_db() as db:
        cursor = await db.execute("DELETE FROM actividades WHERE id = ?", (act_id,))
        await db.commit()
        return cursor.rowcount > 0

async def actualizar_actividad(
    act_id: int,
    fecha: str,
    categoria: str,
    descripcion: str,
    participantes: int
) -> bool:
    """Actualiza los datos de una actividad."""
    await agregar_categoria(categoria)
    async with await get_db() as db:
        cursor = await db.execute(
            """
            UPDATE actividades 
            SET fecha = ?, categoria = ?, descripcion = ?, participantes = ?
            WHERE id = ?
            """,
            (fecha, categoria, descripcion, participantes, act_id)
        )
        await db.commit()
        return cursor.rowcount > 0
