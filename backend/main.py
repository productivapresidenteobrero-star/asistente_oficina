import logging
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import (
    SERVER_HOST, SERVER_PORT, DOCUMENTOS_PATH, MEDIA_PATH, 
    INFORMES_PATH, CARTAS_PATH, AI_QUOTAS, API_KEY
)
from backend.database import init_db, get_db
from backend.indexer import indexar_todos_documentos
from backend.search import responder_consulta, buscar_documentos
from backend.letters import crear_y_guardar_carta
from backend.activities import registrar_actividad, obtener_actividades, listar_categorias, agregar_categoria
from backend.reports import generar_informe_pdf
from backend.telegram_bot import inicializar_bot
from backend.calendar_sync import sincronizar_tareas_con_calendario
from backend.padron import router as padron_router
from backend.consultas import router as consultas_router
from backend.agent import consultar as agent_consultar
from backend.actas import router as actas_router
from backend.universal_agent import consulta_universal, buscar_en_carpeta
from backend.scheduler import iniciar_scheduler

# Configuración de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Instancia global del bot para limpieza
bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejo de inicio y parada de servicios (DB y Telegram Bot)."""
    global bot_app
    
    # 1. Inicializar base de datos
    logger.info("Inicializando Base de Datos...")
    await init_db()
    
    # 2. Indexar documentos al inicio en segundo plano (Desactivado para evitar bucles)
    # logger.info("Lanzando indexación de documentos en segundo plano...")
    # try:
    #     import asyncio
    #     asyncio.create_task(indexar_todos_documentos())
    # except Exception as e:
    #     logger.error(f"Error al lanzar la indexación inicial: {e}")
        
    # 3. Inicializar e iniciar Bot de Telegram
    logger.info("Iniciando Bot de Telegram...")
    bot_app = inicializar_bot()
    if bot_app:
        try:
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling()
            logger.info("Bot de Telegram iniciado exitosamente.")
        except Exception as e:
            logger.error(f"No se pudo iniciar el Bot de Telegram: {e}")

    # 4. Iniciar scheduler de notificaciones proactivas
    logger.info("Iniciando scheduler de notificaciones...")
    asyncio.create_task(iniciar_scheduler())

    yield
    
    # 4. Detener Bot de Telegram al cerrar
    if bot_app:
        logger.info("Deteniendo Bot de Telegram...")
        try:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("Bot de Telegram detenido.")
        except Exception as e:
            logger.error(f"Error al detener el Bot de Telegram: {e}")

app = FastAPI(
    title="Asistente Comunal — Comuna Productiva Presidente Obrero",
    description="Backend API de asistencia y gestión comunal.",
    version="1.0.0",
    lifespan=lifespan
)

# Configurar CORS (localhost-only, sin wildcard + credentials)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth opcional: si API_KEY está definida en .env, protege todas las rutas /api/*
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api/") and request.url.path != "/api/status":
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "API Key inválida o ausente"})
    return await call_next(request)

# Servir archivos generados e imágenes
app.mount("/media", StaticFiles(directory=str(MEDIA_PATH)), name="media")
app.mount("/informes", StaticFiles(directory=str(INFORMES_PATH)), name="informes")
app.mount("/cartas", StaticFiles(directory=str(CARTAS_PATH)), name="cartas")

# Asegurar carpetas
MEDIA_PATH.mkdir(parents=True, exist_ok=True)
INFORMES_PATH.mkdir(parents=True, exist_ok=True)
CARTAS_PATH.mkdir(parents=True, exist_ok=True)

# Registrar routers adicionales
app.include_router(padron_router)
app.include_router(consultas_router)
app.include_router(actas_router)

# Modelos Pydantic
class ConsultaRAG(BaseModel):
    pregunta: str

class NuevaActividad(BaseModel):
    fecha: str
    categoria: str
    descripcion: str
    participantes: int
    fotos: Optional[List[str]] = []

class EditarActividad(BaseModel):
    fecha: str
    categoria: str
    descripcion: str
    participantes: int

class NuevaCarta(BaseModel):
    tipo: str
    destinatario: str
    cargo_destinatario: Optional[str] = ""
    asunto: str
    instrucciones: str
    vocero_firma_id: Optional[int] = None

class NuevaTarea(BaseModel):
    titulo: str
    descripcion: Optional[str] = ""
    fecha_limite: str # YYYY-MM-DD HH:MM
    recordatorio_dias: Optional[int] = 1

# ============================================================
# Endpoints de la API
# ============================================================

@app.get("/api/status")
async def get_status():
    """Retorna el estado general de las APIs de IA y el sistema."""
    return {
        "status": "online",
        "cuotas_ia": AI_QUOTAS,
        "directorio_documentos": str(DOCUMENTOS_PATH),
        "idioma": "es"
    }

@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """Retorna estadísticas clave para el panel principal (KPIs)."""
    mes_actual = datetime.now().strftime("%Y-%m")
    hoy = datetime.now().strftime("%Y-%m-%d")
    
    async with await get_db() as db:
        # Actividades este mes
        c = await db.execute(
            "SELECT COUNT(*) FROM actividades WHERE fecha LIKE ?", (f"{mes_actual}%",)
        )
        actividades_mes = (await c.fetchone())[0]
        
        # Participantes este mes
        c = await db.execute(
            "SELECT COALESCE(SUM(participantes), 0) FROM actividades WHERE fecha LIKE ?",
            (f"{mes_actual}%",)
        )
        participantes_mes = (await c.fetchone())[0]
        
        # Cartas emitidas este mes
        c = await db.execute(
            "SELECT COUNT(*) FROM cartas WHERE fecha LIKE ?", (f"{mes_actual}%",)
        )
        cartas_mes = (await c.fetchone())[0]
        
        # Tareas pendientes
        c = await db.execute(
            "SELECT COUNT(*) FROM tareas WHERE completada=0"
        )
        tareas_pendientes = (await c.fetchone())[0]
        
        # Total documentos indexados
        c = await db.execute("SELECT COUNT(*) FROM documentos")
        total_docs = (await c.fetchone())[0]
        
        # Voceros activos en el padrón
        c = await db.execute("SELECT COUNT(*) FROM voceros WHERE activo=1")
        total_voceros = (await c.fetchone())[0]
        
        # Consejos activos
        c = await db.execute("SELECT COUNT(*) FROM consejos_comunales WHERE activo=1")
        total_consejos = (await c.fetchone())[0]
        
        # Últimas 5 actividades
        c = await db.execute(
            "SELECT fecha, categoria, descripcion, participantes FROM actividades ORDER BY id DESC LIMIT 5"
        )
        ultimas_actividades = [dict(r) for r in await c.fetchall()]
        
        # Uso de IA hoy
        c = await db.execute(
            "SELECT proveedor, llamadas FROM ai_usage WHERE fecha=? ORDER BY llamadas DESC",
            (hoy,)
        )
        uso_ia_hoy = [dict(r) for r in await c.fetchall()]
    
    return {
        "actividades_mes": actividades_mes,
        "participantes_mes": participantes_mes,
        "cartas_mes": cartas_mes,
        "tareas_pendientes": tareas_pendientes,
        "total_documentos": total_docs,
        "total_voceros": total_voceros,
        "total_consejos": total_consejos,
        "ultimas_actividades": ultimas_actividades,
        "uso_ia_hoy": uso_ia_hoy
    }

@app.post("/api/documents/index")
async def trigger_index(background_tasks: BackgroundTasks):
    """Lanza la indexación de la carpeta de documentos en segundo plano."""
    background_tasks.add_task(indexar_todos_documentos)
    return {"message": "Indexación iniciada en segundo plano."}

@app.post("/api/search")
async def post_search(query: ConsultaRAG):
    """Endpoint de búsqueda y consulta inteligente (RAG)."""
    if not query.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")
    try:
        resultado = await responder_consulta(query.pregunta)
        return resultado
    except Exception as e:
        logger.error(f"Error procesando búsqueda RAG: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/activities")
async def get_activities(fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None, categoria: Optional[str] = None):
    """Lista las actividades registradas con filtros."""
    try:
        return await obtener_actividades(fecha_inicio, fecha_fin, categoria)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/activities")
async def post_activity(act: NuevaActividad):
    """Registra una actividad."""
    try:
        from backend.activities import registrar_actividad
        return await registrar_actividad(
            fecha=act.fecha,
            categoria=act.categoria,
            descripcion=act.descripcion,
            participantes=act.participantes,
            fotos=act.fotos
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/activities/{act_id}")
async def delete_activity(act_id: int):
    """Elimina una actividad."""
    from backend.activities import eliminar_actividad
    success = await eliminar_actividad(act_id)
    if not success:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    return {"message": "Actividad eliminada"}

@app.put("/api/activities/{act_id}")
async def put_activity(act_id: int, act: EditarActividad):
    """Actualiza una actividad."""
    from backend.activities import actualizar_actividad
    success = await actualizar_actividad(act_id, act.fecha, act.categoria, act.descripcion, act.participantes)
    if not success:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    return {"message": "Actividad actualizada"}

@app.post("/api/activities/upload-photo")
async def upload_activity_photo(file: UploadFile = File(...)):
    """Sube una foto de actividad y retorna la ruta local."""
    import uuid
    
    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensión no permitida: {ext}. Usa: {', '.join(ALLOWED_EXTENSIONS)}")
    
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"Archivo demasiado grande (máx 10MB)")
    
    unique_id = uuid.uuid4().hex[:6]
    filename = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{unique_id}{ext}"
    filepath = MEDIA_PATH / filename
    
    with open(filepath, "wb") as buffer:
        buffer.write(content)
        
    return {"filepath": str(filepath.resolve())}

@app.get("/api/activities/categories")
async def get_categories():
    """Retorna las categorías de actividades."""
    return await listar_categorias()

@app.post("/api/activities/categories")
async def post_category(nombre: str = Form(...)):
    """Agrega una nueva categoría de actividad."""
    success = await agregar_categoria(nombre)
    if not success:
        raise HTTPException(status_code=400, detail="La categoría ya existe o es inválida.")
    return {"message": f"Categoría '{nombre}' agregada con éxito."}

@app.post("/api/reports")
async def generate_report(periodo: str = Form(...)):
    """Genera un informe en PDF de un periodo determinado."""
    if periodo not in ["diario", "semanal", "mensual", "anual"]:
        raise HTTPException(status_code=400, detail="Período no válido.")
    try:
        res = await generar_informe_pdf(periodo)
        return res
    except Exception as e:
        logger.error(f"Error generando informe: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/letters")
async def post_letter(letter: NuevaCarta):
    """Genera una carta oficial y su respectivo PDF."""
    try:
        res = await crear_y_guardar_carta(
            tipo=letter.tipo,
            destinatario=letter.destinatario,
            cargo_destinatario=letter.cargo_destinatario,
            asunto=letter.asunto,
            instrucciones=letter.instrucciones,
            vocero_firma_id=letter.vocero_firma_id
        )
        return res
    except Exception as e:
        logger.error(f"Error generando carta: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/letters/list")
async def list_letters():
    """Lista las cartas generadas registradas en la base de datos."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM cartas ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

# ============================================================
# Endpoint del Agente Inteligente
# ============================================================

class AgentQuery(BaseModel):
    consulta: str

@app.post("/api/agent/query")
async def post_agent_query(data: AgentQuery):
    """Procesa una consulta en lenguaje natural sobre los expedientes comunales."""
    if not data.consulta.strip():
        raise HTTPException(status_code=400, detail="La consulta no puede estar vacía.")
    try:
        resultado = await agent_consultar(data.consulta)
        return resultado
    except Exception as e:
        logger.error(f"Error en agente: {e}")
        raise HTTPException(status_code=500, detail="Error interno al procesar la consulta")

# ═══════════════════════════════════════════════════════════════════════════════
# AGENTE UNIVERSAL
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/universal/consulta")
async def api_consulta_universal(request: Request):
    """
    Agente Universal: busca en TODAS las fuentes simultáneamente.
    Body: {"query": "...", "formato": "markdown", "incluir_raw": false}
    """
    try:
        body = await request.json()
        query = (body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Se requiere el campo 'query'")
        if len(query) > 1000:
            raise HTTPException(status_code=400, detail="La consulta es demasiado larga (máx. 1000 chars)")

        resultado = await consulta_universal(
            query=query,
            formato=body.get("formato", "markdown"),
            incluir_raw=body.get("incluir_raw", False),
        )
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en consulta universal: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno en el agente de búsqueda")


@app.post("/api/universal/carpeta")
async def api_buscar_en_carpeta(request: Request):
    """
    Busca texto en archivos de una carpeta sin indexación previa.
    Body: {"query": "...", "carpeta": "...", "extensiones": [".pdf"]}
    """
    try:
        body = await request.json()
        query = (body.get("query") or "").strip()
        carpeta = (body.get("carpeta") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Se requiere el campo 'query'")
        if not carpeta:
            raise HTTPException(status_code=400, detail="Se requiere el campo 'carpeta'")
        resultado = await buscar_en_carpeta(
            query=query,
            carpeta=Path(carpeta).resolve(),
            extensiones=body.get("extensiones"),
        )
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error buscando en carpeta: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno buscando en carpeta")


@app.get("/api/universal/estado")
async def api_estado_agente():
    """Devuelve métricas del sistema para el dashboard."""
    try:
        from backend.database import get_db
        async with await get_db() as db:
            stats = {}
            for tabla in ["voceros", "consejos_comunales", "cartas", "actividades", "documentos"]:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {tabla}")
                row = await cursor.fetchone()
                stats[tabla] = row[0] if row else 0
            hoy = date.today().isoformat()
            cursor = await db.execute("SELECT COUNT(*) FROM tareas WHERE completada=0")
            stats["tareas_pendientes"] = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM tareas WHERE completada=0 AND fecha_limite < ?", (hoy,)
            )
            stats["tareas_vencidas"] = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT proveedor, llamadas FROM ai_usage WHERE fecha=?", (hoy,)
            )
            stats["uso_ia_hoy"] = {r[0]: r[1] for r in await cursor.fetchall()}
        return {"ok": True, "stats": stats}
    except Exception as e:
        logger.error(f"Error obteniendo estado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error obteniendo estadísticas")

# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tasks")
async def get_tasks():
    """Obtiene el listado de tareas del calendario."""
    async with await get_db() as db:
        cursor = await db.execute("SELECT * FROM tareas ORDER BY fecha_limite ASC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

@app.post("/api/tasks")
async def post_task(task: NuevaTarea, background_tasks: BackgroundTasks):
    """Crea una tarea programada y la sincroniza al calendario."""
    async with await get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO tareas (titulo, descripcion, fecha_limite, recordatorio_dias)
            VALUES (?, ?, ?, ?)
            """,
            (task.titulo, task.descripcion, task.fecha_limite, task.recordatorio_dias)
        )
        await db.commit()
        
    # Lanzar sincronización en segundo plano
    background_tasks.add_task(sincronizar_tareas_con_calendario)
    return {"message": "Tarea agendada y en proceso de sincronización con Google Calendar."}

@app.put("/api/tasks/{task_id}/complete")
async def complete_task(task_id: int):
    """Marca una tarea como completada."""
    async with await get_db() as db:
        await db.execute("UPDATE tareas SET completada = 1 WHERE id = ?", (task_id,))
        await db.commit()
    return {"message": "Tarea marcada como completada."}

# Servir Frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists() and (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    logger.info("Frontend estático montado correctamente.")
else:
    logger.warning("No se encontró el directorio de frontend. El servidor solo actuará como API.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
