import httpx
import logging
from datetime import date
from typing import Optional
from backend.config import (
    GROQ_API_KEY,
    GEMINI_API_KEY,
    COHERE_API_KEY,
    HUGGINGFACE_API_KEY,
    ZHIPU_API_KEY,
    AI_PRIORITY,
    AI_QUOTAS
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_router")

# ── Persistencia de cuotas ──────────────────────────────────────────────────
async def _get_uso_hoy(proveedor: str) -> int:
    """Lee cuántas llamadas se hicieron hoy al proveedor desde la DB."""
    try:
        from backend.database import get_db
        hoy = date.today().isoformat()
        async with await get_db() as db:
            cursor = await db.execute(
                "SELECT llamadas FROM ai_usage WHERE fecha=? AND proveedor=?",
                (hoy, proveedor)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.warning(f"No se pudo leer cuota de DB para {proveedor}: {e}")
        return AI_QUOTAS.get(proveedor, {}).get("used", 0)

async def _incrementar_uso(proveedor: str):
    """Incrementa en 1 el contador de llamadas de hoy en la DB."""
    try:
        from backend.database import get_db
        hoy = date.today().isoformat()
        async with await get_db() as db:
            await db.execute(
                """
                INSERT INTO ai_usage (fecha, proveedor, llamadas)
                VALUES (?, ?, 1)
                ON CONFLICT(fecha, proveedor)
                DO UPDATE SET llamadas = llamadas + 1
                """,
                (hoy, proveedor)
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"No se pudo guardar cuota en DB para {proveedor}: {e}")
    # También actualizar el contador en memoria
    if proveedor in AI_QUOTAS:
        AI_QUOTAS[proveedor]["used"] += 1

# Historial de fallos temporales para no reintentar inmediatamente con una API rota
API_STATUS = {provider: True for provider in AI_PRIORITY}

async def call_groq(prompt: str, system: str) -> Optional[str]:
    """Llama a la API de Groq usando Llama 3."""
    if not GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": 0.3
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            AI_QUOTAS["groq"]["used"] += 1
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Groq API Error: {response.status_code} - {response.text}")
            return None

async def call_gemini(prompt: str, system: str) -> Optional[str]:
    """Llama a la API de Google Gemini (1.5 Flash)."""
    if not GEMINI_API_KEY:
        return None
    # Intentar con varios modelos/versiones de API
    modelos_gemini = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.0-flash-lite",
    ]
    
    for modelo in modelos_gemini:
        url = f"https://generativelanguage.googleapis.com/v1/models/{modelo}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        
        if system:
            data = {
                "contents": [{"parts": [{"text": f"Instrucción del sistema: {system}\n\nPregunta: {prompt}"}]}],
                "generationConfig": {"temperature": 0.3}
            }
        else:
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3}
            }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=data)
            if response.status_code == 200:
                AI_QUOTAS["gemini"]["used"] += 1
                res_json = response.json()
                try:
                    return res_json["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as e:
                    logger.error(f"Gemini parsing error: {e}. Response: {res_json}")
                    return None
            else:
                logger.warning(f"Gemini API Error con {modelo}: {response.status_code}")
    
    logger.error("Todos los modelos Gemini fallaron")
    return None

async def call_cohere(prompt: str, system: str) -> Optional[str]:
    """Llama a la API de Cohere (Command R)."""
    if not COHERE_API_KEY:
        return None
    url = "https://api.cohere.com/v2/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": "command-r",
        "messages": messages,
        "temperature": 0.3
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            AI_QUOTAS["cohere"]["used"] += 1
            return response.json()["message"]["content"][0]["text"]
        else:
            logger.error(f"Cohere API Error: {response.status_code} - {response.text}")
            return None

async def call_huggingface(prompt: str, system: str) -> Optional[str]:
    """Llama a un modelo de Hugging Face (como Mistral-7B)."""
    if not HUGGINGFACE_API_KEY:
        return None
    # Mistral-7B-Instruct o similar
    url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    full_prompt = f"<s>[INST] {system}\n\n{prompt} [/INST]" if system else f"<s>[INST] {prompt} [/INST]"
    data = {
        "inputs": full_prompt,
        "parameters": {"max_new_tokens": 1024, "temperature": 0.3}
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            AI_QUOTAS["huggingface"]["used"] += 1
            res = response.json()
            # La respuesta de HF suele ser una lista con el texto generado
            if isinstance(res, list) and len(res) > 0:
                generated_text = res[0].get("generated_text", "")
                # Eliminar el prompt de la respuesta si el modelo lo incluye
                if generated_text.startswith(full_prompt):
                    generated_text = generated_text[len(full_prompt):]
                return generated_text.strip()
            return str(res)
        else:
            logger.error(f"HuggingFace API Error: {response.status_code} - {response.text}")
            return None

async def call_zhipu(prompt: str, system: str) -> Optional[str]:
    """Llama a la API de Zhipu AI (GLM-4-Flash)."""
    if not ZHIPU_API_KEY:
        return None
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": "glm-4-flash",
        "messages": messages,
        "temperature": 0.3
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            AI_QUOTAS["zhipu"]["used"] += 1
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Zhipu API Error: {response.status_code} - {response.text}")
            return None

# Mapeo de llamadas
CALL_FUNCTIONS = {
    "zhipu": call_zhipu,
    "groq": call_groq,
    "gemini": call_gemini,
    "cohere": call_cohere,
    "huggingface": call_huggingface
}

async def generar_texto(prompt: str, system_instruction: str = "") -> str:
    """
    Genera texto usando el sistema rotativo de APIs.
    Si un proveedor falla o supera su cuota, intenta con el siguiente.
    Persiste el uso en la tabla ai_usage de SQLite.
    """
    errores = []
    for provider in AI_PRIORITY:
        # Verificar límite de cuotas (DB + memoria)
        quota_config = AI_QUOTAS.get(provider, {"limit": 0})
        uso_hoy = await _get_uso_hoy(provider)
        if uso_hoy >= quota_config.get("limit", 0):
            logger.warning(f"Proveedor {provider} omitido: cuota diaria alcanzada ({uso_hoy}/{quota_config.get('limit', 0)}).")
            continue

        logger.info(f"Intentando generar texto con proveedor: {provider} (uso hoy: {uso_hoy})")
        try:
            func = CALL_FUNCTIONS[provider]
            resultado = await func(prompt, system_instruction)
            if resultado is not None:
                await _incrementar_uso(provider)
                return resultado
        except Exception as e:
            logger.error(f"Excepción al llamar al proveedor {provider}: {str(e)}")
            errores.append(f"{provider}: {str(e)}")

    # Si todo falla, lanzar un error
    error_msg = f"Todos los proveedores de IA fallaron. Errores: {', '.join(errores)}"
    logger.critical(error_msg)
    raise RuntimeError(error_msg)
