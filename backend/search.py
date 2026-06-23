import logging
from typing import List, Dict
from backend.indexer import collection
from backend.database import get_db
from backend.ai_router import generar_texto

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("search")

async def buscar_documentos_fts(query: str, top_k: int = 5) -> List[dict]:
    """Búsqueda en SQLite FTS5 (búsqueda de texto clásica)."""
    resultados = []
    # Reemplazar espacios por OR/AND para formatear la consulta FTS5
    # Por simplicidad, buscamos coincidencias con cada palabra clave o la frase exacta
    palabras = [p for p in query.split() if len(p) > 2]
    if not palabras:
        palabras = [query]
        
    consulta_fts = " OR ".join([f'"{p}*"' for p in palabras])
    
    async with await get_db() as db:
        try:
            cursor = await db.execute(
                """
                SELECT nombre, ruta, pagina, contenido, 
                       fts_documentos.rank as score
                FROM fts_documentos 
                WHERE fts_documentos MATCH ? 
                ORDER BY rank 
                LIMIT ?
                """,
                (consulta_fts, top_k)
            )
            rows = await cursor.fetchall()
            for r in rows:
                resultados.append({
                    "nombre": r["nombre"],
                    "ruta": r["ruta"],
                    "pagina": r["pagina"],
                    "contenido": r["contenido"],
                    "metodo": "FTS5",
                    "score": float(r["score"]) if r["score"] else 0.0
                })
        except Exception as e:
            logger.error(f"Error en búsqueda FTS5: {e}")
            
    return resultados

async def buscar_documentos(query: str, top_k: int = 5) -> List[dict]:
    """
    Busca documentos utilizando búsqueda semántica (ChromaDB) 
    con fallback automático a FTS5 (SQLite).
    """
    resultados = []
    
    # 1. Intentar LanceDB
    if collection is not None:
        try:
            res = collection.search(query).limit(top_k).to_list()
            if res and len(res) > 0:
                for row in res:
                    resultados.append({
                        "nombre": row["nombre"],
                        "ruta": row["ruta"],
                        "pagina": row["pagina"],
                        "contenido": row["texto"],
                        "metodo": "LanceDB",
                        "score": float(row.get("_distance", 0.0))
                    })
                
                # Integrar re-rankeo semántico si Cohere está configurado
                from backend.config import COHERE_API_KEY
                if COHERE_API_KEY and COHERE_API_KEY != "tu_clave_cohere_aqui":
                    try:
                        from lancedb.rerankers import CohereReranker
                        import os
                        os.environ["COHERE_API_KEY"] = COHERE_API_KEY
                        reranker = CohereReranker(model_name="rerank-multilingual-v3.0")
                        # Realizar búsqueda con rerank
                        reranked_res = collection.search(query).limit(top_k * 3).rerank(reranker=reranker).to_list()
                        if reranked_res:
                            resultados = []
                            for row in reranked_res[:top_k]:
                                resultados.append({
                                    "nombre": row["nombre"],
                                    "ruta": row["ruta"],
                                    "pagina": row["pagina"],
                                    "contenido": row["texto"],
                                    "metodo": "LanceDB + Reranker",
                                    "score": float(row.get("_relevance_score", 0.0))
                                })
                            logger.info(f"Búsqueda semántica exitosa y re-rankeada con Cohere: {len(resultados)} resultados.")
                            return resultados
                    except Exception as re_err:
                        logger.warning(f"No se pudo hacer rerank con Cohere: {re_err}. Usando ordenación original.")

                logger.info(f"Búsqueda semántica exitosa (LanceDB): {len(resultados)} resultados.")
                return resultados
        except Exception as e:
            logger.error(f"Fallo en LanceDB query: {e}. Pasando a FTS5.")
            
    # 2. Fallback a FTS5 si ChromaDB falla o no está disponible
    return await buscar_documentos_fts(query, top_k)

async def responder_consulta(query: str) -> dict:
    """
    Toma una pregunta del usuario, busca contexto en los documentos
    y genera una respuesta fundamentada (RAG) usando el pool de IAs.
    """
    logger.info(f"Procesando consulta RAG para: {query}")
    documentos = await buscar_documentos(query, top_k=5)
    
    if not documentos:
        # Si no hay documentos, intentar responder de forma general con la IA
        prompt = f"El usuario pregunta: '{query}'. Responde de forma amable indicando que no encontraste documentos específicos al respecto en los archivos de la comuna, pero responde lo mejor que puedas basándote en tu conocimiento general."
        respuesta = await generar_texto(prompt, system_instruction="Eres el Asistente de la Comuna Productiva Presidente Obrero. Responde en español.")
        return {
            "respuesta": respuesta,
            "fuentes": []
        }
        
    # Construir el contexto
    contexto_str = ""
    fuentes = set()
    for idx, doc in enumerate(documentos):
        contexto_str += f"--- Documento {idx+1}: {doc['nombre']} (Pág. {doc['pagina']}) ---\n"
        contexto_str += f"{doc['contenido']}\n\n"
        fuentes.add(f"{doc['nombre']} (Pág. {doc['pagina']})")
        
    prompt = f"""
Pregunta del usuario: {query}

Contexto extraído de los archivos de la comuna:
{contexto_str}

Instrucciones:
Responde la pregunta basándote estrictamente en el contexto proporcionado. Si la respuesta no se encuentra en el contexto, indícalo de manera honesta, pero aporta cualquier información útil relacionada. Sé claro, profesional y estructurado. Responde siempre en español.
"""

    system_instruction = (
        "Eres el Asistente Digital de la Comuna Productiva Presidente Obrero. Tu tarea es ayudar "
        "al vocero comunal respondiendo preguntas de manera precisa basándote en las actas, "
        "oficios y reportes de la comuna."
    )
    
    respuesta = await generar_texto(prompt, system_instruction=system_instruction)
    
    return {
        "respuesta": respuesta,
        "fuentes": list(fuentes)
    }
