import logging
import json
import re
import asyncio
from typing import Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("universal_agent")


# ─────────────────────────────────────────────────────────────────────────────
# PASO 1: Clasificador de intención
# ─────────────────────────────────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "voceros": [
        "vocero", "vocalía", "vocería", "principal", "suplente", "electo",
        "elegido", "cargo", "cédula", "teléfono", "contacto", "miembro",
        "consejo comunal", "quién es", "quién fue", "quiénes son",
    ],
    "actas": [
        "acta", "asamblea", "elección", "votación", "votos", "elegido",
        "acta de elección", "reunión", "sesión", "resolución", "aprobó",
    ],
    "cartas": [
        "carta", "oficio", "solicitud", "correspondencia", "comunicado",
        "CPPO", "número de oficio", "dirigida", "destinatario", "envió",
        "escribió", "redactó",
    ],
    "actividades": [
        "actividad", "jornada", "evento", "censo", "obra", "construcción",
        "taller", "formación", "visita", "rendición de cuentas", "realiz",
        "hicieron", "hizo", "participantes",
    ],
    "tareas": [
        "tarea", "pendiente", "plazo", "vencimiento", "recordatorio",
        "programado", "calendario", "agenda", "compromiso", "deadline",
    ],
    "documentos": [
        "documento", "archivo", "informe", "reporte", "pdf", "word",
        "excel", "planilla", "presupuesto", "proyecto", "plan",
        "qué dice", "qué contiene", "busca en", "encuentra en",
    ],
}


def _clasificar_intencion(query: str) -> dict:
    q = query.lower()
    scores = {fuente: 0.0 for fuente in INTENT_KEYWORDS}

    for fuente, keywords in INTENT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in q)
        scores[fuente] = min(hits / max(len(keywords) * 0.3, 1), 1.0)

    if max(scores.values()) < 0.05:
        scores["documentos"] = 0.5
        scores["voceros"] = 0.3

    if any(p in q for p in ["quién", "quien", "quiénes", "quienes"]):
        scores["voceros"] = max(scores["voceros"], 0.6)

    if any(p in q for p in ["cuándo", "cuando", "fecha", "día", "mes"]):
        scores["actas"] = max(scores["actas"], 0.4)
        scores["tareas"] = max(scores["tareas"], 0.4)

    fuentes_activas = {f: s for f, s in scores.items() if s > 0.1}
    if not fuentes_activas:
        fuentes_activas = {f: 0.2 for f in INTENT_KEYWORDS}

    logger.info(f"Fuentes activas para '{query[:50]}': {fuentes_activas}")
    return fuentes_activas


# ─────────────────────────────────────────────────────────────────────────────
# PASO 2: Búsquedas por fuente
# ─────────────────────────────────────────────────────────────────────────────

async def _buscar_voceros(query: str) -> list:
    resultados = []
    q = query.lower()
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT v.nombre, v.cedula, v.cargo, v.tipo, v.telefono, v.votos,
                       c.nombre as consejo_nombre, a.fecha_acta, a.pdf_path
                FROM voceros v
                LEFT JOIN consejos_comunales c ON v.consejo_id = c.id
                LEFT JOIN actas a ON v.acta_id = a.id
                WHERE v.activo = 1
                  AND (
                    LOWER(v.nombre)   LIKE '%' || ? || '%'
                    OR LOWER(v.cedula) LIKE '%' || ? || '%'
                    OR LOWER(v.cargo)  LIKE '%' || ? || '%'
                    OR LOWER(c.nombre) LIKE '%' || ? || '%'
                  )
                LIMIT 50
                """,
                (q, q, q, q),
            )
            rows = await cursor.fetchall()

            if not rows:
                cursor = await db.execute(
                    """
                    SELECT v.nombre, v.cedula, v.cargo, v.tipo, v.telefono, v.votos,
                           c.nombre as consejo_nombre, a.fecha_acta, a.pdf_path
                    FROM voceros v
                    LEFT JOIN consejos_comunales c ON v.consejo_id = c.id
                    LEFT JOIN actas a ON v.acta_id = a.id
                    WHERE v.activo = 1
                    LIMIT 200
                    """
                )
                rows = await cursor.fetchall()

            for r in rows:
                resultados.append({
                    "fuente": "voceros",
                    "tipo_doc": "Padrón de Voceros",
                    "nombre": (r[0] or "").strip(),
                    "cedula": (r[1] or "").strip(),
                    "cargo": (r[2] or "").strip(),
                    "tipo": (r[3] or "Principal").strip(),
                    "telefono": (r[4] or "").strip(),
                    "votos": int(r[5] or 0),
                    "consejo": (r[6] or "").strip(),
                    "fecha_acta": (r[7] or "").strip(),
                    "pdf_acta": (r[8] or "").strip(),
                    "resumen": (
                        f"{r[0]} — {r[2]} ({r[3]}) en {r[6] or 'N/A'}"
                        + (f", C.I: {r[1]}" if r[1] else "")
                        + (f", Tel: {r[4]}" if r[4] else "")
                    ),
                })
    except Exception as e:
        logger.error(f"Error buscando voceros: {e}")
    return resultados


async def _buscar_actas(query: str) -> list:
    resultados = []
    q = f"%{query.lower()}%"
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT a.codigo_registro, a.fecha_acta, a.nombre_consejo,
                       a.sector, a.pdf_path, c.nombre as consejo_nombre
                FROM actas a
                LEFT JOIN consejos_comunales c ON a.consejo_id = c.id
                WHERE LOWER(a.nombre_consejo) LIKE ?
                   OR LOWER(a.sector) LIKE ?
                   OR LOWER(c.nombre) LIKE ?
                ORDER BY a.fecha_acta DESC
                LIMIT 20
                """,
                (q, q, q),
            )
            rows = await cursor.fetchall()
            for r in rows:
                resultados.append({
                    "fuente": "actas",
                    "tipo_doc": "Acta de Elección",
                    "codigo": (r[0] or ""),
                    "fecha": (r[1] or ""),
                    "consejo": (r[2] or r[5] or ""),
                    "sector": (r[3] or ""),
                    "pdf_path": (r[4] or ""),
                    "resumen": f"Acta del {r[1]} — {r[2] or r[5]} (sector: {r[3] or 'N/A'})",
                })
    except Exception as e:
        logger.error(f"Error buscando actas: {e}")
    return resultados


async def _buscar_cartas(query: str) -> list:
    resultados = []
    q = f"%{query.lower()}%"
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT numero_oficio, tipo, fecha, destinatario,
                       asunto, contenido, pdf_path
                FROM cartas
                WHERE LOWER(destinatario) LIKE ?
                   OR LOWER(asunto)       LIKE ?
                   OR LOWER(contenido)    LIKE ?
                   OR LOWER(numero_oficio) LIKE ?
                ORDER BY fecha DESC
                LIMIT 15
                """,
                (q, q, q, q),
            )
            rows = await cursor.fetchall()
            for r in rows:
                resultados.append({
                    "fuente": "cartas",
                    "tipo_doc": f"Carta / Oficio ({r[1]})",
                    "numero": r[0],
                    "tipo": r[1],
                    "fecha": r[2],
                    "destinatario": r[3],
                    "asunto": r[4],
                    "preview": (r[5] or "")[:200].replace("\n", " "),
                    "pdf_path": r[6],
                    "resumen": f"[{r[0]}] {r[4]} — Para: {r[3]} ({r[2]})",
                })
    except Exception as e:
        logger.error(f"Error buscando cartas: {e}")
    return resultados


async def _buscar_actividades(query: str) -> list:
    resultados = []
    q = f"%{query.lower()}%"
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT fecha, categoria, descripcion, participantes
                FROM actividades
                WHERE LOWER(descripcion) LIKE ?
                   OR LOWER(categoria)   LIKE ?
                ORDER BY fecha DESC
                LIMIT 20
                """,
                (q, q),
            )
            rows = await cursor.fetchall()
            for r in rows:
                resultados.append({
                    "fuente": "actividades",
                    "tipo_doc": "Actividad Comunal",
                    "fecha": r[0],
                    "categoria": r[1],
                    "descripcion": r[2],
                    "participantes": r[3],
                    "resumen": f"[{r[1]}] {r[2][:100]} — {r[0]} ({r[3]} participantes)",
                })
    except Exception as e:
        logger.error(f"Error buscando actividades: {e}")
    return resultados


async def _buscar_tareas(query: str) -> list:
    resultados = []
    q = f"%{query.lower()}%"
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """
                SELECT titulo, descripcion, fecha_limite, completada
                FROM tareas
                WHERE LOWER(titulo)      LIKE ?
                   OR LOWER(descripcion) LIKE ?
                ORDER BY fecha_limite ASC
                LIMIT 20
                """,
                (q, q),
            )
            rows = await cursor.fetchall()
            for r in rows:
                estado = "✅ Completada" if r[3] else "⏳ Pendiente"
                resultados.append({
                    "fuente": "tareas",
                    "tipo_doc": "Tarea / Compromiso",
                    "titulo": r[0],
                    "descripcion": r[1],
                    "fecha_limite": r[2],
                    "completada": bool(r[3]),
                    "resumen": f"{estado} — {r[0]} (vence: {r[2]})",
                })
    except Exception as e:
        logger.error(f"Error buscando tareas: {e}")
    return resultados


async def _buscar_documentos_rag(query: str) -> list:
    resultados = []
    try:
        from backend.search import buscar_documentos
        docs = await buscar_documentos(query, top_k=8)
        for d in docs:
            resultados.append({
                "fuente": "documentos",
                "tipo_doc": f"Documento ({d.get('metodo', 'FTS5')})",
                "nombre": d["nombre"],
                "ruta": d["ruta"],
                "pagina": d["pagina"],
                "contenido": d["contenido"],
                "score": d.get("score", 0.0),
                "resumen": f"[{d['nombre']}] pág. {d['pagina']} — {d['contenido'][:120]}...",
            })
    except Exception as e:
        logger.error(f"Error en búsqueda RAG: {e}")
    return resultados


# ─────────────────────────────────────────────────────────────────────────────
# PASO 3: Fusión y ranking
# ─────────────────────────────────────────────────────────────────────────────

def _fusionar_resultados(
    resultados_por_fuente: dict,
    scores_fuentes: dict,
    limite: int = 30,
) -> list:
    todos = []
    seen = set()

    for fuente, resultados in resultados_por_fuente.items():
        peso = scores_fuentes.get(fuente, 0.1)
        for r in resultados:
            clave = r.get("resumen", "")[:80].lower().strip()
            if clave in seen:
                continue
            seen.add(clave)
            score_interno = r.get("score", 0.5)
            r["_score"] = peso * (1 - score_interno) if fuente == "documentos" else peso
            todos.append(r)

    todos.sort(key=lambda x: x["_score"], reverse=True)
    return todos[:limite]


# ─────────────────────────────────────────────────────────────────────────────
# PASO 4: Generación de respuesta con IA
# ─────────────────────────────────────────────────────────────────────────────

async def _generar_respuesta_ia(
    query: str,
    resultados: list,
    formato: str = "markdown",
) -> str:
    from backend.ai_router import generar_texto

    contexto_parts = []
    for i, r in enumerate(resultados[:15], 1):
        fuente_label = r.get("tipo_doc", r.get("fuente", "Fuente"))
        contexto_parts.append(f"[{i}] {fuente_label}: {r['resumen']}")
        if r.get("fuente") == "documentos" and r.get("contenido"):
            contexto_parts.append(f"    Contenido: {r['contenido'][:300]}")
        if r.get("fuente") == "cartas" and r.get("preview"):
            contexto_parts.append(f"    Extracto: {r['preview']}")

    contexto_str = "\n".join(contexto_parts) if contexto_parts else "No se encontraron datos relevantes."

    system = """Eres el Asistente Digital de la Comuna Productiva Presidente Obrero.
Tienes acceso a los datos comunales: padrón de voceros, actas de elección,
cartas y oficios, actividades, tareas y documentos archivados.

Reglas:
1. Responde SIEMPRE en español, de forma clara y estructurada.
2. Cita la fuente de cada dato.
3. Si la información está en múltiples fuentes, sintetiza y organiza.
4. Si no encuentras algo específico, dilo claramente.
5. Usa formato Markdown: **negritas**, tablas, listas según corresponda.
6. Sé conciso pero completo. Prioriza la información más reciente."""

    prompt = f"""CONSULTA: {query}

INFORMACIÓN ENCONTRADA:
{contexto_str}

Genera una respuesta completa basada en estos datos.
Indica cuántas fuentes se consultaron y cuáles tenían información relevante."""

    try:
        respuesta = await generar_texto(prompt, system_instruction=system)
        return respuesta
    except Exception as e:
        logger.error(f"Error generando respuesta IA: {e}")
        lines = [f"**Resultados encontrados para:** *{query}*\n"]
        for r in resultados[:15]:
            lines.append(f"- **{r.get('tipo_doc', 'Dato')}**: {r['resumen']}")
        if not resultados:
            lines.append("No se encontraron resultados en ninguna fuente.")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

async def consulta_universal(
    query: str,
    formato: str = "markdown",
    incluir_raw: bool = False,
) -> dict:
    inicio = datetime.now()
    logger.info(f"[UniversalAgent] Consulta: '{query}'")

    scores_fuentes = _clasificar_intencion(query)

    mapa_funciones = {
        "voceros":    _buscar_voceros,
        "actas":      _buscar_actas,
        "cartas":     _buscar_cartas,
        "actividades": _buscar_actividades,
        "tareas":     _buscar_tareas,
        "documentos": _buscar_documentos_rag,
    }

    coros = {
        fuente: mapa_funciones[fuente](query)
        for fuente in scores_fuentes
        if fuente in mapa_funciones
    }

    resultados_por_fuente = {}
    if coros:
        resultados_lista = await asyncio.gather(*coros.values(), return_exceptions=True)
        for fuente, resultado in zip(coros.keys(), resultados_lista):
            if isinstance(resultado, Exception):
                logger.error(f"Fuente '{fuente}' falló: {resultado}")
                resultados_por_fuente[fuente] = []
            else:
                resultados_por_fuente[fuente] = resultado

    resultados_fusionados = _fusionar_resultados(
        resultados_por_fuente, scores_fuentes, limite=30
    )

    fuentes_con_datos = [f for f, r in resultados_por_fuente.items() if r]

    respuesta = await _generar_respuesta_ia(query, resultados_fusionados, formato)

    tiempo_ms = int((datetime.now() - inicio).total_seconds() * 1000)
    logger.info(
        f"[UniversalAgent] Completado en {tiempo_ms}ms. "
        f"Fuentes con datos: {fuentes_con_datos}. "
        f"Total hallazgos: {len(resultados_fusionados)}"
    )

    salida = {
        "respuesta": respuesta,
        "fuentes_usadas": fuentes_con_datos,
        "fuentes_consultadas": list(scores_fuentes.keys()),
        "total_hallazgos": len(resultados_fusionados),
        "tiempo_ms": tiempo_ms,
    }

    if incluir_raw:
        raw = [{k: v for k, v in r.items() if k != "_score"} for r in resultados_fusionados]
        salida["raw_results"] = raw

    return salida


# ─────────────────────────────────────────────────────────────────────────────
# BÚSQUEDA EN CARPETA (sin indexar)
# ─────────────────────────────────────────────────────────────────────────────

async def buscar_en_carpeta(
    query: str,
    carpeta: str,
    extensiones: Optional[list] = None,
) -> dict:
    from backend.indexer import (
        extraer_texto_pdf, extraer_texto_docx,
        extraer_texto_excel, extraer_texto_txt, extraer_texto_imagen,
    )

    carpeta_path = Path(carpeta)
    if not carpeta_path.exists():
        return {
            "respuesta": f"La carpeta `{carpeta}` no existe o no es accesible.",
            "archivos_revisados": 0,
            "coincidencias": [],
        }

    exts_soportadas = extensiones or [
        ".pdf", ".docx", ".doc", ".xlsx", ".xls",
        ".csv", ".txt", ".md", ".png", ".jpg", ".jpeg",
    ]

    extractores = {
        ".pdf":  extraer_texto_pdf,
        ".docx": extraer_texto_docx,
        ".doc":  extraer_texto_docx,
        ".xlsx": extraer_texto_excel,
        ".xls":  extraer_texto_excel,
        ".csv":  extraer_texto_excel,
        ".txt":  extraer_texto_txt,
        ".md":   extraer_texto_txt,
        ".png":  extraer_texto_imagen,
        ".jpg":  extraer_texto_imagen,
        ".jpeg": extraer_texto_imagen,
    }

    q_lower = query.lower()
    coincidencias = []
    archivos_revisados = 0

    for filepath in sorted(carpeta_path.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() not in exts_soportadas:
            continue

        archivos_revisados += 1
        extractor = extractores.get(filepath.suffix.lower())
        if not extractor:
            continue

        try:
            paginas = await asyncio.to_thread(extractor, filepath)
            for pag in paginas:
                texto = pag.get("texto", "")
                if q_lower in texto.lower():
                    idx = texto.lower().find(q_lower)
                    inicio_ctx = max(0, idx - 100)
                    fin_ctx = min(len(texto), idx + 200)
                    fragmento = "..." + texto[inicio_ctx:fin_ctx].replace("\n", " ") + "..."
                    coincidencias.append({
                        "archivo": filepath.name,
                        "ruta": str(filepath),
                        "pagina": pag.get("pagina", 1),
                        "fragmento": fragmento,
                    })
                    break
        except Exception as e:
            logger.warning(f"No se pudo leer {filepath.name}: {e}")

    if coincidencias:
        contexto = "\n".join(
            f"- {c['archivo']} (pág. {c['pagina']}): {c['fragmento']}"
            for c in coincidencias[:10]
        )
        from backend.ai_router import generar_texto
        try:
            respuesta = await generar_texto(
                f"El usuario busca '{query}' en la carpeta '{carpeta_path.name}'.\n\n"
                f"Se encontraron coincidencias en estos archivos:\n{contexto}\n\n"
                f"Resume qué información encontraste y en qué archivos.",
                system_instruction=(
                    "Eres el Asistente de la Comuna. Responde en español, "
                    "citando los archivos donde encontraste la información."
                ),
            )
        except Exception:
            respuesta = (
                f"Se encontraron **{len(coincidencias)} archivos** con coincidencias "
                f"para '{query}' en `{carpeta_path.name}`."
            )
    else:
        respuesta = (
            f"No se encontró '{query}' en ninguno de los "
            f"{archivos_revisados} archivos revisados en `{carpeta_path.name}`."
        )

    return {
        "respuesta": respuesta,
        "archivos_revisados": archivos_revisados,
        "coincidencias": coincidencias,
    }
