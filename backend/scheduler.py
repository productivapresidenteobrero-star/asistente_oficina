import asyncio
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger("scheduler")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de DB
# ─────────────────────────────────────────────────────────────────────────────

async def _tareas_por_vencer(dias: int = 3) -> list:
    try:
        from backend.database import get_db
        hoy = date.today().isoformat()
        limite = (date.today() + timedelta(days=dias)).isoformat()
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT titulo, descripcion, fecha_limite
                FROM tareas
                WHERE completada = 0
                  AND fecha_limite BETWEEN ? AND ?
                ORDER BY fecha_limite ASC
                """,
                (hoy, limite),
            )
            rows = await cursor.fetchall()
            return [{"titulo": r[0], "descripcion": r[1] or "", "fecha_limite": r[2]} for r in rows]
    except Exception as e:
        logger.error(f"Error obteniendo tareas: {e}")
        return []


async def _tareas_vencidas() -> list:
    try:
        from backend.database import get_db
        hoy = date.today().isoformat()
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT titulo, fecha_limite
                FROM tareas
                WHERE completada = 0
                  AND fecha_limite < ?
                ORDER BY fecha_limite ASC
                LIMIT 10
                """,
                (hoy,),
            )
            rows = await cursor.fetchall()
            return [{"titulo": r[0], "fecha_limite": r[1]} for r in rows]
    except Exception as e:
        logger.error(f"Error obteniendo tareas vencidas: {e}")
        return []


async def _actividades_recientes(dias: int = 1) -> list:
    try:
        from backend.database import get_db
        desde = (date.today() - timedelta(days=dias)).isoformat()
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT fecha, categoria, descripcion, participantes
                FROM actividades
                WHERE fecha >= ?
                ORDER BY fecha DESC
                LIMIT 10
                """,
                (desde,),
            )
            rows = await cursor.fetchall()
            return [{"fecha": r[0], "categoria": r[1], "descripcion": r[2], "participantes": r[3]} for r in rows]
    except Exception as e:
        logger.error(f"Error obteniendo actividades: {e}")
        return []


async def _estadisticas_generales() -> dict:
    try:
        from backend.database import get_db
        async with await get_db() as db:
            stats = {}
            for tabla, campo in [
                ("voceros", "voceros activos"),
                ("consejos_comunales", "consejos"),
                ("cartas", "cartas emitidas"),
                ("actividades", "actividades"),
            ]:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {tabla}")
                row = await cursor.fetchone()
                stats[campo] = row[0] if row else 0
            cursor = await db.execute("SELECT COUNT(*) FROM tareas WHERE completada = 0")
            row = await cursor.fetchone()
            stats["tareas pendientes"] = row[0] if row else 0
            return stats
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Envío a Telegram
# ─────────────────────────────────────────────────────────────────────────────

async def _enviar_telegram(mensaje: str):
    try:
        import httpx
        from backend.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram no configurado. Omitiendo notificación.")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                logger.error(f"Error enviando a Telegram: {r.text}")
    except Exception as e:
        logger.error(f"Excepción enviando a Telegram: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Mensajes
# ─────────────────────────────────────────────────────────────────────────────

async def _notificacion_matutina():
    hoy = date.today().strftime("%A %d de %B de %Y")
    tareas_hoy = await _tareas_por_vencer(dias=1)
    tareas_semana = await _tareas_por_vencer(dias=7)
    vencidas = await _tareas_vencidas()
    stats = await _estadisticas_generales()

    lineas = [f"☀️ <b>Buenos días — {hoy}</b>", "", "📊 <b>Estado del sistema:</b>"]
    for k, v in stats.items():
        lineas.append(f"  • {k.capitalize()}: <b>{v}</b>")

    if tareas_hoy:
        lineas += ["", "🔴 <b>Vencen HOY:</b>"]
        for t in tareas_hoy:
            lineas.append(f"  ⚠️ {t['titulo']} <i>({t['fecha_limite']})</i>")

    if tareas_semana and not tareas_hoy:
        lineas += ["", "📅 <b>Próximos vencimientos (7 días):</b>"]
        for t in tareas_semana[:5]:
            lineas.append(f"  • {t['titulo']} — {t['fecha_limite']}")

    if vencidas:
        lineas += ["", f"❌ <b>Tareas vencidas sin completar: {len(vencidas)}</b>"]
        for t in vencidas[:3]:
            lineas.append(f"  • {t['titulo']} (venció {t['fecha_limite']})")

    if not tareas_hoy and not vencidas:
        lineas += ["", "✅ <b>No hay tareas urgentes hoy.</b>"]

    lineas += ["", "Usa /consulta [pregunta] para buscar cualquier dato de la comuna."]
    await _enviar_telegram("\n".join(lineas))
    logger.info("Notificación matutina enviada.")


async def _alerta_vencimientos():
    tareas = await _tareas_por_vencer(dias=0)
    if not tareas:
        return
    lineas = [f"🚨 <b>Alerta: {len(tareas)} tarea(s) vence(n) HOY</b>", ""]
    for t in tareas:
        lineas.append(f"• <b>{t['titulo']}</b>")
        if t["descripcion"]:
            lineas.append(f"  {t['descripcion'][:80]}")
    await _enviar_telegram("\n".join(lineas))
    logger.info(f"Alerta de vencimientos enviada: {len(tareas)} tareas.")


async def _resumen_vespertino():
    actividades = await _actividades_recientes(dias=1)
    tareas_pendientes = await _tareas_por_vencer(dias=3)

    lineas = ["🌆 <b>Resumen del día</b>", ""]
    if actividades:
        lineas.append(f"📌 <b>Actividades registradas hoy ({len(actividades)}):</b>")
        for a in actividades[:5]:
            lineas.append(
                f"  • [{a['categoria']}] {a['descripcion'][:60]}"
                + (f" ({a['participantes']} participantes)" if a["participantes"] else "")
            )
    else:
        lineas.append("📌 No se registraron actividades hoy.")

    if tareas_pendientes:
        lineas += ["", f"⏰ <b>Pendientes próximos días ({len(tareas_pendientes)}):</b>"]
        for t in tareas_pendientes[:3]:
            lineas.append(f"  • {t['titulo']} — vence {t['fecha_limite']}")

    await _enviar_telegram("\n".join(lineas))
    logger.info("Resumen vespertino enviado.")


async def _chequeo_silencioso():
    try:
        vencidas = await _tareas_vencidas()
        criticas = [t for t in vencidas if t["fecha_limite"] < (date.today() - timedelta(days=7)).isoformat()]
        if criticas:
            lineas = [f"⚠️ <b>Hay {len(criticas)} tarea(s) vencida(s) hace más de 7 días:</b>"]
            for t in criticas[:5]:
                lineas.append(f"  • {t['titulo']} (venció {t['fecha_limite']})")
            await _enviar_telegram("\n".join(lineas))
    except Exception as e:
        logger.error(f"Error en chequeo silencioso: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Loop principal
# ─────────────────────────────────────────────────────────────────────────────

async def iniciar_scheduler():
    logger.info("Scheduler de notificaciones iniciado.")
    ejecutadas_hoy: dict = {}

    while True:
        try:
            ahora = datetime.now()
            hoy_str = ahora.strftime("%Y-%m-%d")
            hora = ahora.hour
            minuto = ahora.minute

            if ejecutadas_hoy.get("fecha") != hoy_str:
                ejecutadas_hoy = {"fecha": hoy_str}

            if hora == 8 and minuto < 5 and not ejecutadas_hoy.get("matutina"):
                ejecutadas_hoy["matutina"] = True
                await _notificacion_matutina()

            if hora == 9 and minuto < 5 and not ejecutadas_hoy.get("alerta"):
                ejecutadas_hoy["alerta"] = True
                await _alerta_vencimientos()

            if hora == 18 and minuto < 5 and not ejecutadas_hoy.get("vespertino"):
                ejecutadas_hoy["vespertino"] = True
                await _resumen_vespertino()

            hora_key = f"chequeo_{hora}"
            if minuto < 5 and not ejecutadas_hoy.get(hora_key):
                ejecutadas_hoy[hora_key] = True
                await _chequeo_silencioso()

        except Exception as e:
            logger.error(f"Error en scheduler: {e}")

        await asyncio.sleep(60)
