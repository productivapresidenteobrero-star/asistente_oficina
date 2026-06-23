import os
import logging
import json
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from backend.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MEDIA_PATH
from backend.database import get_db
from backend.ai_router import generar_texto
from backend.search import responder_consulta
from backend.activities import registrar_actividad, listar_categorias
from backend.calendar_sync import agregar_evento_calendario

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram_bot")

MEDIA_PATH.mkdir(parents=True, exist_ok=True)

# Helper to verify if the message comes from the authorized vocero/chat
def es_chat_autorizado(chat_id: int) -> bool:
    if not TELEGRAM_CHAT_ID:
        # Si no se configuró chat_id, se auto-configura con el primero que hable
        return True
    return str(chat_id) == str(TELEGRAM_CHAT_ID)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el mensaje de bienvenida y comandos del bot."""
    chat_id = update.effective_chat.id
    
    # Auto-vincular si no está configurado
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID:
        TELEGRAM_CHAT_ID = str(chat_id)
        logger.info(f"Telegram Chat ID auto-configurado con el ID: {chat_id}")
        
    if not es_chat_autorizado(chat_id):
        await update.message.reply_text("Acceso no autorizado.")
        return

    bienvenida = (
        "🇻🇪 **¡Bienvenido al Asistente Comunal!** 🇻🇪\n"
        "Comuna Productiva Presidente Obrero\n\n"
        "Estoy a tu disposición para ayudarte a gestionar la comuna desde tu celular. "
        "Aquí tienes los comandos disponibles:\n\n"
        "🔍 **Búsquedas e Información:**\n"
        "• Justo escríbeme cualquier pregunta sobre las actas u oficios y buscaré en los documentos para darte la respuesta.\n"
        "• `/buscar [término]` - Busca directamente en los archivos.\n\n"
        "📝 **Registrar Actividades:**\n"
        "• Envía una foto con una descripción del evento y la registraré automáticamente con imágenes.\n"
        "• `/actividad [descripción]` - Registra una actividad comunal (asamblea, obra, reunión, etc.).\n\n"
        "📅 **Calendario y Tareas:**\n"
        "• `/tarea [detalles]` - Agrega un recordatorio / tarea al calendario. Intentaré extraer la fecha automáticamente.\n"
        "• `/tareas` - Ver las próximas tareas pendientes.\n\n"
        "¡Escríbeme lo que necesites!"
    )
    await update.message.reply_text(bienvenida, parse_mode="Markdown")

async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Realiza una consulta a los documentos o la DB."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
        
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Por favor escribe qué deseas buscar. Ejemplo: `/buscar actas de asamblea`")
        return
        
    await update.message.reply_chat_action("typing")
    
    # Usar el agente que consulta la DB
    from backend.agent import consultar
    res = await consultar(query)
    respuesta_completa = res.get("respuesta", "No pude procesar esa consulta.")
    if res.get("tabla"):
        respuesta_completa = res["tabla"]
    
    # Acortar si es demasiado largo
    if len(respuesta_completa) > 4000:
        respuesta_completa = respuesta_completa[:4000] + "\n\n[Respuesta recortada...]"
        
    await update.message.reply_text(respuesta_completa, parse_mode="Markdown")

async def registrar_actividad_inteligente(texto: str, fotos: list = None) -> str:
    """Usa la IA para extraer metadatos de un texto libre y guardar la actividad."""
    categorias = await listar_categorias()
    categorias_str = ", ".join(categorias)
    
    prompt = f"""
Analiza el siguiente texto de actividad comunitaria y extrae los siguientes datos en formato JSON válido:
{{
  "fecha": "YYYY-MM-DD (si no se menciona, usa la fecha actual {datetime.now().strftime('%Y-%m-%d')})",
  "categoria": "Debe ser una de estas: {categorias_str}. Elige la que mejor se adapte.",
  "descripcion_resumida": "Resumen claro y bien redactado en español",
  "participantes": número de participantes estimado (0 si no se indica)
}}

Texto a analizar:
"{texto}"
"""
    try:
        res_ia = await generar_texto(prompt, system_instruction="Retorna ÚNICAMENTE un JSON válido.")
        # Limpiar posibles markdown del JSON
        res_ia = res_ia.replace("```json", "").replace("```", "").strip()
        data = json.loads(res_ia)
        
        # Guardar en base de datos
        act = await registrar_actividad(
            fecha=data.get("fecha"),
            categoria=data.get("categoria", "Otro"),
            descripcion=data.get("descripcion_resumida", texto),
            participantes=data.get("participantes", 0),
            fotos=fotos
        )
        
        info = (
            f"✅ **Actividad Registrada Exitosamente**\n"
            f"📅 **Fecha:** {act['fecha']}\n"
            f"🏷️ **Categoría:** {act['categoria']}\n"
            f"👥 **Participantes:** {act['participantes']}\n"
            f"📝 **Resumen:** {act['descripcion']}"
        )
        if fotos:
            info += f"\n📸 Se adjuntaron {len(fotos)} imagen(es)."
        return info
    except Exception as e:
        logger.error(f"Error registrando actividad inteligente: {e}")
        # Registro básico de respaldo
        act = await registrar_actividad(
            fecha=datetime.now().strftime("%Y-%m-%d"),
            categoria="Otro",
            descripcion=texto,
            participantes=0,
            fotos=fotos
        )
        return f"✅ Actividad guardada (modo simple):\n{texto}"

async def actividad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra una actividad por comando."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
    texto = " ".join(context.args) if context.args else ""
    if not texto:
        await update.message.reply_text("Por favor detalla la actividad. Ejemplo: `/actividad Hoy realizamos una asamblea con 40 vecinos para tratar el agua`")
        return
        
    await update.message.reply_chat_action("typing")
    res = await registrar_actividad_inteligente(texto)
    await update.message.reply_text(res, parse_mode="Markdown")

async def registrar_tarea_inteligente(texto: str) -> str:
    """Extrae fecha y detalles de una tarea programada y la sincroniza al calendario."""
    prompt = f"""
Analiza la siguiente instrucción de tarea y extrae los detalles en formato JSON válido:
{{
  "titulo": "Título corto de la tarea",
  "descripcion": "Detalle o descripción extendida",
  "fecha_limite": "YYYY-MM-DD HH:MM (Calcula basándote en la fecha/hora actual: {datetime.now().strftime('%Y-%m-%d %H:%M')})",
  "recordatorio_dias": 1
}}

Instrucción de tarea:
"{texto}"
"""
    try:
        res_ia = await generar_texto(prompt, system_instruction="Retorna ÚNICAMENTE un JSON válido.")
        res_ia = res_ia.replace("```json", "").replace("```", "").strip()
        data = json.loads(res_ia)
        
        titulo = data.get("titulo", "Tarea Comunal")
        descripcion = data.get("descripcion", texto)
        fecha_limite = data.get("fecha_limite")
        rec_dias = data.get("recordatorio_dias", 1)
        
        # Guardar en SQLite
        async with await get_db() as db:
            cursor = await db.execute(
                """
                INSERT INTO tareas (titulo, descripcion, fecha_limite, recordatorio_dias)
                VALUES (?, ?, ?, ?)
                """,
                (titulo, descripcion, fecha_limite, rec_dias)
            )
            await db.commit()
            tarea_id = cursor.lastrowid
            
        info = (
            f"📅 **Tarea Agendada**\n"
            f"📌 **Título:** {titulo}\n"
            f"⏰ **Fecha Límite:** {fecha_limite}\n"
            f"🔔 **Recordatorio:** {rec_dias} día(s) antes.\n\n"
            f"Intentando sincronizar con Google Calendar..."
        )
        
        # Intentar sincronización con Google Calendar
        try:
            # Convertir a ISO
            dt = datetime.strptime(fecha_limite, "%Y-%m-%d %H:%M")
            fecha_iso = dt.strftime("%Y-%m-%dT%H:%M:00")
            event_id = await agregar_evento_calendario(titulo, descripcion, fecha_iso)
            if event_id:
                async with await get_db() as db:
                    await db.execute("UPDATE tareas SET sincronizado_calendar = 1 WHERE id = ?", (tarea_id,))
                    await db.commit()
                info += "\n✅ Sincronizado con Google Calendar."
            else:
                info += "\n⚠️ Guardada localmente (Google Calendar no configurado)."
        except Exception as cal_err:
            logger.error(f"Error sincronizando calendario: {cal_err}")
            info += "\n⚠️ Guardada localmente (Error de conexión con Google Calendar)."
            
        return info
    except Exception as e:
        logger.error(f"Error registrando tarea inteligente: {e}")
        return "❌ No pude interpretar la fecha de la tarea. Intenta ser más específico (ej. '/tarea Reunión el 2026-06-15 a las 10:00')."

async def tarea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra una tarea."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
    texto = " ".join(context.args) if context.args else ""
    if not texto:
        await update.message.reply_text("Por favor escribe la tarea y su fecha. Ejemplo: `/tarea Asamblea ordinaria el próximo lunes a las 6 pm`")
        return
        
    await update.message.reply_chat_action("typing")
    res = await registrar_tarea_inteligente(texto)
    await update.message.reply_text(res, parse_mode="Markdown")

async def tareas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista las próximas tareas comunales pendientes."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
        
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT titulo, fecha_limite FROM tareas WHERE completada = 0 ORDER BY fecha_limite ASC LIMIT 10"
        )
        rows = await cursor.fetchall()
        
        if not rows:
            await update.message.reply_text("No tienes tareas pendientes agendadas. ¡Buen trabajo!")
            return
            
        msg = "📅 **Próximas Tareas Pendientes:**\n\n"
        for idx, r in enumerate(rows):
            msg += f"{idx+1}. **{r['titulo']}**\n   ⏰ Limite: {r['fecha_limite']}\n\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")

async def recibir_mensaje_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Descarga fotos adjuntas y registra la descripción como una actividad."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
        
    # Obtener el pie de foto o descripción
    texto = update.message.caption or ""
    if not texto:
        await update.message.reply_text(
            "Recibí tu foto, pero necesito una descripción para poder guardarla como actividad. "
            "Por favor, vuelve a enviarla agregándole un mensaje descriptivo."
        )
        return
        
    await update.message.reply_text("Guardando foto y procesando actividad comunitaria...")
    await update.message.reply_chat_action("upload_photo")
    
    try:
        # Descargar foto de mayor resolución
        photo_file = await update.message.photo[-1].get_file()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        foto_nombre = f"img_{timestamp}.jpg"
        foto_ruta = MEDIA_PATH / foto_nombre
        
        await photo_file.download_to_drive(str(foto_ruta))
        logger.info(f"Imagen descargada de Telegram en: {foto_ruta}")
        
        # Registrar como actividad
        resultado = await registrar_actividad_inteligente(texto, fotos=[str(foto_ruta.resolve())])
        await update.message.reply_text(resultado, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error procesando foto recibida: {e}")
        await update.message.reply_text("❌ Ocurrió un error al intentar guardar la foto.")

async def recibir_mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensajes de texto planos que no son comandos se responden usando RAG/Búsqueda."""
    if not es_chat_autorizado(update.effective_chat.id):
        return
        
    texto = update.message.text
    if not texto:
        return
        
    await update.message.reply_chat_action("typing")
    
    # Palabras clave que indican consulta a la DB (voceros, oficios, actas, consejos)
    palabras_db = ["vocero", "voceros", "vocería", "voceria", "consejo comunal", "consejo",
                   "oficio", "oficios", "carta", "cartas", "acta", "actas", "elección",
                   "eleccion", "comuna", "electo", "elegido", "padrón", "padron",
                   "cuantos", "cuántos", "registro", "registrados", "ultimo", "último",
                   "numero de oficio", "número de oficio", "ecosocialismo", "salud",
                   "juventud", "contraloría", "contraloria", "principal", "suplente",
                   "cédula", "cedula", "teléfono", "telefono", "votos", "votación"]
    
    texto_lower = texto.lower()
    es_consulta_db = any(p in texto_lower for p in palabras_db)
    
    if es_consulta_db:
        # Usar el agente que consulta la DB
        from backend.agent import consultar
        res = await consultar(texto)
        respuesta_completa = res.get("respuesta", "No pude procesar esa consulta.")
        if res.get("tabla"):
            respuesta_completa = res["tabla"]
    else:
        # Usar RAG para búsqueda en documentos
        res = await responder_consulta(texto)
        fuentes_str = ""
        if res["fuentes"]:
            fuentes_str = "\n\n📄 **Fuentes:**\n" + "\n".join([f"• {f}" for f in res["fuentes"]])
        respuesta_completa = f"{res['respuesta']}{fuentes_str}"
    
    # Acortar si es demasiado largo para Telegram (límite 4096 caracteres)
    if len(respuesta_completa) > 4000:
        respuesta_completa = respuesta_completa[:4000] + "\n\n[Respuesta recortada...]"

    try:
        await update.message.reply_text(respuesta_completa, parse_mode="Markdown")
    except Exception:
        # Fallback a texto plano si Markdown falla (nombres con _ o caracteres especiales)
        await update.message.reply_text(respuesta_completa)

async def enviar_notificaciones_periodicas(context: ContextTypes.DEFAULT_TYPE):
    """Envía notificaciones al chat de Telegram sobre tareas próximas a vencer."""
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
        
    hoy = datetime.now()
    
    async with await get_db() as db:
        # Buscar tareas no completadas y que no hayan sido notificadas
        cursor = await db.execute(
            "SELECT id, titulo, descripcion, fecha_limite, recordatorio_dias FROM tareas WHERE completada = 0 AND telegram_notificado = 0"
        )
        tareas = await cursor.fetchall()
        
        for t in tareas:
            t_id = t["id"]
            titulo = t["titulo"]
            limite_str = t["fecha_limite"]
            rec_dias = t["recordatorio_dias"]
            
            try:
                dt_limite = datetime.strptime(limite_str, "%Y-%m-%d %H:%M")
                diferencia = dt_limite - hoy
                
                # Si estamos dentro del rango del recordatorio, notificar
                if diferencia.total_seconds() > 0 and diferencia.days <= rec_dias:
                    mensaje = (
                        f"⏰ **RECORDATORIO DE TAREA** ⏰\n\n"
                        f"La tarea **{titulo}** vence pronto.\n"
                        f"📅 **Límite:** {limite_str}\n"
                        f"📝 **Detalle:** {t['descripcion'] or 'Sin detalles'}\n\n"
                        f"¡No lo olvides!"
                    )
                    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode="Markdown")
                    
                    # Marcar como notificada
                    await db.execute("UPDATE tareas SET telegram_notificado = 1 WHERE id = ?", (t_id,))
            except Exception as e:
                logger.error(f"Error procesando recordatorio para tarea {t_id}: {e}")
                
        await db.commit()

# Inicialización y ejecución del Bot en segundo plano
bot_application = None

def inicializar_bot():
    """Configura y retorna la aplicación del bot de Telegram."""
    global bot_application
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado. El bot de Telegram no se iniciará.")
        return None
        
    try:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Registrar manejadores de comandos
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("buscar", buscar_command))
        app.add_handler(CommandHandler("actividad", actividad_command))
        app.add_handler(CommandHandler("tarea", tarea_command))
        app.add_handler(CommandHandler("tareas", tareas_command))
        
        # Manejador de imágenes
        app.add_handler(MessageHandler(filters.PHOTO, recibir_mensaje_foto))
        
        # Manejador de texto plano (para RAG y chat directo)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_mensaje_texto))
        
        # Programar alertas de tareas cada 15 minutos (900 segundos)
        app.job_queue.run_repeating(enviar_notificaciones_periodicas, interval=900, first=10)
        
        bot_application = app
        logger.info("Bot de Telegram configurado exitosamente.")
        return app
    except Exception as e:
        logger.error(f"Error inicializando el Bot de Telegram: {e}")
        return None
