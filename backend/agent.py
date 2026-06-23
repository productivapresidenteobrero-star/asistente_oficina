"""
Agente Inteligente de Consultas Comunales
Busca en la base de datos SQLite (actas de elección) y responde
preguntas en lenguaje natural sobre voceros, consejos y estructura comunal.
"""
import logging
import json
import re
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger("agent")

_data_cache = {"voceros": None, "loaded_at": None}

COLUMNS = {
    "nombre_completo": "Nombre completo",
    "cedula": "Número de cédula",
    "telefono": "Número de teléfono",
    "voceria": "Vocería a la que fue electo",
    "tipo": "Principal o Suplente",
    "votos": "Votos obtenidos",
    "consejo_comunal": "Nombre del Consejo Comunal",
}


async def _cargar_voceros_db() -> List[Dict[str, Any]]:
    """Carga voceros desde SQLite (actas de elección)."""
    voceros_db = []
    try:
        from backend.database import get_db
        async with await get_db() as db:
            cursor = await db.execute(
                """SELECT v.nombre, v.cedula, v.cargo, v.tipo, v.telefono, v.votos,
                          c.nombre as consejo_nombre
                   FROM voceros v
                   LEFT JOIN consejos_comunales c ON v.consejo_id = c.id
                   WHERE v.activo=1"""
            )
            rows = await cursor.fetchall()
            for r in rows:
                nombre = (r[0] or "").strip()
                if not nombre:
                    continue
                voceros_db.append({
                    "nombre_completo": nombre,
                    "cedula": (r[1] or "").strip(),
                    "voceria": (r[2] or "").strip(),
                    "tipo": (r[3] or "Principal").strip(),
                    "telefono": (r[4] or "").strip(),
                    "votos": int(r[5] or 0),
                    "consejo_comunal": (r[6] or "").strip(),
                })
        logger.info(f"Cargados {len(voceros_db)} voceros desde SQLite")
    except Exception as e:
        logger.warning(f"No se pudieron cargar voceros desde SQLite: {e}")
    return voceros_db


async def _asegurar_datos():
    now = datetime.now()
    if _data_cache["voceros"] is None:
        _data_cache["voceros"] = await _cargar_voceros_db()
        _data_cache["loaded_at"] = now
    elif (now - _data_cache["loaded_at"]).total_seconds() > 60:
        _data_cache["voceros"] = await _cargar_voceros_db()
        _data_cache["loaded_at"] = now


async def _valores_columna(col_key: str) -> List[str]:
    await _asegurar_datos()
    vals = set()
    for v in _data_cache["voceros"]:
        val = str(v.get(col_key, "")).strip()
        if val:
            vals.add(val)
    return sorted(vals)


async def consultar(query: str) -> dict:
    """
    Procesa una consulta en lenguaje natural sobre los expedientes comunales.
    """
    from backend.ai_router import generar_texto

    await _asegurar_datos()
    voceros = _data_cache["voceros"]

    if not voceros:
        return {
            "respuesta": "No hay voceros registrados en la base de datos. Sube un acta de elección en PDF para comenzar.",
            "tabla": None,
            "total_resultados": 0,
        }

    consejos = await _valores_columna("consejo_comunal")
    vocerias = await _valores_columna("voceria")

    def filtrar(filtros: List[dict]) -> List[dict]:
        resultados = voceros
        for f in filtros:
            campo = f.get("campo", "")
            operador = f.get("operador", "igual")
            valor = f.get("valor", "").strip().lower()
            if not campo or not valor:
                continue
            if operador == "contiene":
                resultados = [
                    r for r in resultados if valor in r.get(campo, "").strip().lower()
                ]
            elif operador == "igual":
                resultados = [
                    r for r in resultados
                    if r.get(campo, "").strip().lower() == valor
                ]
            elif operador == "empieza":
                resultados = [
                    r for r in resultados
                    if r.get(campo, "").strip().lower().startswith(valor)
                ]
        return resultados

    def agrupar(datos: List[dict], campo: str) -> dict:
        grupos = {}
        for r in datos:
            key = r.get(campo, "Sin especificar").strip()
            if not key:
                key = "Sin especificar"
            if key not in grupos:
                grupos[key] = []
            grupos[key].append(r)
        return grupos

    # === Step 1: LLM genera el plan de consulta ===
    system_schema = f"""Eres un planificador de consultas para datos comunales.

COLUMNAS DISPONIBLES:
- nombre_completo: Nombre completo del vocero
- cedula: Número de cédula
- telefono: Número de teléfono
- voceria: Vocería a la que fue electo (ej: "Ecosocialismo", "Salud", etc.)
- tipo: "Principal" o "Suplente"
- votos: Cantidad de votos obtenidos (número entero)
- consejo_comunal: Nombre del Consejo Comunal

VOCERÍAS DISPONIBLES:
{chr(10).join(f'  - {v}' for v in vocerias[:50])}

CONSEJOS DISPONIBLES:
{chr(10).join(f'  - {c}' for c in consejos[:50])}

Debes analizar la consulta del usuario y generar un plan JSON con filtros y operaciones.
Siempre responde SOLO con el JSON, sin texto adicional."""

    plan_prompt = f"""CONSULTA DEL USUARIO: {query}

Genera un JSON con esta estructura exacta:
{{
    "filtros": [
        {{"campo": "nombre_del_campo", "operador": "contiene|igual|empieza", "valor": "valor_a_buscar"}}
    ],
    "agrupar_por": null | "consejo_comunal" | "voceria" | "tipo",
    "ordenar_por": null | {{"campo": "nombre_completo|votos", "direccion": "asc|desc"}},
    "contar": true | false,
    "limite": null | 50,
    "explicacion": "Explica brevemente qué filtros aplicaste y por qué"
}}

Reglas:
- Si preguntan "cuántos", "total", "conteo", "cantidad", usa "contar": true
- Para buscar una vocería, usa {{"campo": "voceria", "operador": "contiene", "valor": "ecosocialismo"}}
- Para buscar un consejo específico, usa {{"campo": "consejo_comunal", "operador": "contiene", "valor": "manuelita"}}
- Para "Principal" o "Suplente", usa {{"campo": "tipo", "operador": "igual", "valor": "principal"}}
- Para ordenar por votos de mayor a menor, usa {{"campo": "votos", "direccion": "desc"}}
- Para ordenar por votos de menor a mayor, usa {{"campo": "votos", "direccion": "asc"}}
- Si no hay filtros claros, deja filtros como lista vacía"""

    try:
        plan_raw = await generar_texto(plan_prompt, system_instruction=system_schema)
        json_match = re.search(r"\{.*\}", plan_raw, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
        else:
            plan = json.loads(plan_raw)
        logger.info(f"Plan generado por IA: {json.dumps(plan, ensure_ascii=False)}")
    except Exception as e:
        logger.warning(f"IA no disponible, usando fallback por palabras clave: {e}")
        q = query.lower()
        plan = {"filtros": [], "agrupar_por": None, "ordenar_por": None, "contar": False, "limite": 100, "explicacion": ""}

        if any(p in q for p in ["cuantos", "cuántos", "total", "conteo", "cantidad"]):
            plan["contar"] = True
            plan["explicacion"] += "Contando voceros. "
            if "consejo" in q:
                plan["agrupar_por"] = "consejo_comunal"
                plan["explicacion"] += "Agrupando por consejo comunal. "
            elif "voceria" in q or "vocería" in q:
                plan["agrupar_por"] = "voceria"
                plan["explicacion"] += "Agrupando por vocería. "
        elif any(p in q for p in ["por consejo", "por voceria", "por vocería", "cada"]):
            if "consejo" in q:
                plan["agrupar_por"] = "consejo_comunal"
                plan["explicacion"] += "Agrupando por consejo comunal. "
            elif "voceria" in q or "vocería" in q:
                plan["agrupar_por"] = "voceria"
                plan["explicacion"] += "Agrupando por vocería. "

        if any(p in q for p in [" principal", "principales", " solo principal", "vocero principal"]):
            plan["filtros"].append({"campo": "tipo", "operador": "igual", "valor": "principal"})
            plan["explicacion"] += "Mostrando solo principales. "
        elif any(p in q for p in [" suplente", "suplentes"]):
            plan["filtros"].append({"campo": "tipo", "operador": "igual", "valor": "suplente"})
            plan["explicacion"] += "Mostrando solo suplentes. "

        # Detectar orden por votos
        if any(kw in q for kw in ["votos", "votación", "votacion", "mayor a menor", "menor a mayor", "ordenar por voto"]):
            if "menor" in q:
                plan["ordenar_por"] = {"campo": "votos", "direccion": "asc"}
                plan["explicacion"] += "Ordenando por votos (menor a mayor). "
            else:
                plan["ordenar_por"] = {"campo": "votos", "direccion": "desc"}
                plan["explicacion"] += "Ordenando por votos (mayor a menor). "

        if any(kw in q for kw in ["contraloria", "contraloría", "contralor"]):
            plan["filtros"].append({"campo": "voceria", "operador": "contiene", "valor": "contraloria"})
            plan["explicacion"] += "Filtrando por Contraloría. "

        elif not plan.get("agrupar_por"):
            q_lower = q
            for c in sorted(consejos, key=len, reverse=True):
                c_lower = c.lower()
                palabras_clave = c_lower.replace("consejo comunal ", "").strip()
                if len(palabras_clave) > 3 and palabras_clave in q_lower:
                    plan["filtros"].append({"campo": "consejo_comunal", "operador": "contiene", "valor": c_lower[:40]})
                    plan["explicacion"] += f"Filtrando por '{c}'. "
                    break

        if not any(f.get("campo") == "voceria" for f in plan["filtros"]):
            vocerias_lower = {v.lower(): v for v in vocerias}
            vocerias_ordenadas = sorted(vocerias_lower.keys(), key=lambda v: len(v), reverse=True)
            for v_lower in vocerias_ordenadas:
                palabras_v = set(v_lower.split())
                palabras_q = set(q.split())
                coinciden = palabras_v & palabras_q
                if len(coinciden) >= 2 or any(len(p) >= 6 and p in q for p in palabras_v):
                    plan["filtros"].append({"campo": "voceria", "operador": "contiene", "valor": v_lower[:40]})
                    plan["explicacion"] += f"Filtrando por vocería. "
                    break

        if not plan["explicacion"]:
            plan["explicacion"] = "Mostrando todos los voceros."

    # === Step 2: Ejecutar plan ===
    filtros = plan.get("filtros", [])
    agrupar_por = plan.get("agrupar_por")
    ordenar_por = plan.get("ordenar_por")
    contar = plan.get("contar", False)
    limite = plan.get("limite")

    resultados = filtrar(filtros)
    explicacion = plan.get("explicacion", "")

    if ordenar_por:
        campo_ord = ordenar_por.get("campo", "votos")
        direccion = ordenar_por.get("direccion", "desc")
        resultados.sort(
            key=lambda r: r.get(campo_ord, 0) if campo_ord == "votos" else r.get(campo_ord, "").strip().lower(),
            reverse=(direccion == "desc"),
        )

    if limite and len(resultados) > limite:
        resultados = resultados[:limite]

    total = len(resultados)

    # === Step 3: Generar respuesta formateada ===
    if total == 0:
        return {
            "respuesta": f"No encontré voceros que coincidan con los criterios solicitados. {explicacion}",
            "tabla": None,
            "total_resultados": 0,
        }

    # Si es conteo, retornar solo el número
    if contar:
        if agrupar_por:
            grupos = agrupar(resultados, agrupar_por)
            respuesta = f"**{explicacion}**\n\n"
            respuesta += f"**Total de voceros: {total}**\n\n"
            respuesta += f"| {agrupar_por.replace('_', ' ').title()} | Cantidad |\n|---|---|\n"
            for grupo, miembros in sorted(grupos.items()):
                respuesta += f"| {grupo} | {len(miembros)} |\n"
            tabla_md = respuesta
        else:
            respuesta = f"**{explicacion}**\n\n📊 **Total de voceros registrados: {total}**"
            tabla_md = respuesta
        return {
            "respuesta": respuesta,
            "tabla": tabla_md,
            "total_resultados": total,
        }

    if agrupar_por:
        grupos = agrupar(resultados, agrupar_por)
        lines = [f"**Resultados agrupados por {agrupar_por}:**", ""]
        lines.append(f"| {agrupar_por.replace('_', ' ').title()} | Cantidad de Voceros |")
        lines.append("|---|---|")
        for grupo, miembros in sorted(grupos.items()):
            lines.append(f"| {grupo} | {len(miembros)} |")
        lines.append("")
        lines.append(f"**Total de voceros: {total}**")
        tabla_md = "\n".join(lines)

        respuesta = f"""**{explicacion}**

Se encontraron **{total} voceros** agrupados por **{agrupar_por.replace('_', ' ')}**:

"""
        for grupo, miembros in sorted(grupos.items()):
            respuesta += f"\n**{grupo}** ({len(miembros)} voceros):\n"
            for m in miembros[:10]:
                respuesta += f"  - {m['nombre_completo']} ({m.get('voceria', '')})"
                if m.get("cedula"):
                    respuesta += f" - C.I: {m['cedula']}"
                if m.get("votos"):
                    respuesta += f" - {m['votos']} votos"
                respuesta += "\n"
            if len(miembros) > 10:
                respuesta += f"  ... y {len(miembros) - 10} más\n"
    else:
        tabla_md = f"""**{explicacion}**

| # | Nombre Completo | Cédula | Vocería | Tipo | Votos | Consejo Comunal |
|---|---|---|---|---|---|---|
"""
        for i, v in enumerate(resultados, 1):
            tabla_md += f"| {i} | {v['nombre_completo']} | {v['cedula']} | {v['voceria']} | {v['tipo']} | {v.get('votos', 0)} | {v['consejo_comunal']} |\n"
        tabla_md += f"\n**Total: {total} vocero(s)**"

        respuesta = f"""**{explicacion}**

Se encontraron **{total} vocero(s)** que coinciden con los criterios:

"""
        for v in resultados[:15]:
            voto_str = f" - {v['votos']} votos" if v.get("votos") else ""
            respuesta += f"  - **{v['nombre_completo']}** - {v['voceria']} ({v['tipo']}){voto_str} - {v['consejo_comunal']}\n"
        if total > 15:
            respuesta += f"\n... y {total - 15} más. Revisa la tabla completa."

    return {
        "respuesta": respuesta,
        "tabla": tabla_md,
        "total_resultados": total,
    }
