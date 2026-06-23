import re
import logging
from pathlib import Path

logger = logging.getLogger("pdf_extractor")

RE_CODIGO = re.compile(r'[Uu][-]?[Cc][Cc][Oo][- ]?\d{2}[- ]?\d{2}[- ]?\d{2}[- ]?\d{6}')
RE_FECHA = re.compile(r'FECHA[:\s]*(\d{2}[-/]\d{2}[-/]\d{4})', re.IGNORECASE)
RE_CONSEJO = re.compile(r'CONSEJO\s+COMUNAL\s+["\u201c]?([^"\u201d\n]+)["\u201d]?', re.IGNORECASE)
RE_SECTOR = re.compile(r'SECTOR\s+["\u201c]?([^"\u201d\n]+)["\u201d]?', re.IGNORECASE)

def _limpiar_cedula(raw: str) -> str:
    raw = raw.replace('.', '').replace('-', '').replace(' ', '').strip()
    raw = re.sub(r'^[VJEP]+', '', raw)
    return raw.strip()

def _limpiar_nombre(nombre: str) -> str:
    """Extrae cédula basura del nombre y la retorna separada."""
    nombre = nombre.strip()
    m = re.search(r'\s+[VJEP][-.\s]*\d{5,}$', nombre, re.IGNORECASE)
    if m:
        nombre = nombre[:m.start()].strip()
    return nombre.title() if nombre else nombre

def _limpiar_telefono(raw: str) -> str:
    return re.sub(r'[^\d+]', '', raw)

def extraer_datos_acta(pdf_path: str | Path) -> dict:
    import pdfplumber

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"No se encuentra: {pdf_path}")

    texto_completo = ""
    todas_las_palabras = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            texto_completo += (t or "") + "\n"
            words = page.extract_words()
            # Guardar palabras con coordenadas + offset de página
            for w in words:
                todas_las_palabras.append({
                    "text": w["text"],
                    "x0": w["x0"],
                    "top": w["top"],
                    "page_idx": page.page_number - 1,
                    "doctop": w.get("doctop", w["top"] + page.page_number * 800),
                })

    texto_upper = texto_completo.upper()

    if not texto_completo.strip():
        logger.warning("No se detectó texto. Intentando OCR con Zhipu (GLM-4V) como respaldo...")
        return _extraer_datos_con_ocr_zhipu(pdf_path)

    # ── Metadatos ──────────────────────────────────────────
    codigo = _extraer_metadato(RE_CODIGO, texto_upper)
    fecha = _extraer_metadato(RE_FECHA, texto_upper)
    consejo = _extraer_metadato(RE_CONSEJO, texto_upper)
    sector = _extraer_metadato(RE_SECTOR, texto_upper)

    # ── Voceros usando coordenadas ─────────────────────────
    voceros = _extraer_todos_voceros(texto_completo, todas_las_palabras)

    logger.info("Extraídos %d voceros de %s", len(voceros), pdf_path.name)

    return {
        "codigo_registro": codigo or "",
        "fecha_acta": fecha or "",
        "nombre_consejo": consejo or "",
        "sector": sector or "",
        "voceros": voceros
    }

def _extraer_metadato(regex, texto: str) -> str | None:
    m = regex.search(texto)
    return m.group(1).strip() if m and m.lastindex else (m.group(0).strip() if m else None)

# ── Estrategia principal: extraer de TODAS las páginas ────

SECCIONES = [
    "VOCEROS DE LA UNIDAD EJECUTIVA",
    "UNIDAD ADMINISTRATIVA Y FINANCIERA",
    "UNIDAD DE CONTRALORIA SOCIAL",
    "UNIDAD DE COMISION ELECTORAL",
]

def _agrupar_por_filas(palabras: list[dict]) -> list[list[dict]]:
    """Agrupa palabras por fila (coordenada y absoluta) y ordena por x dentro de cada fila."""
    filas = {}
    for w in palabras:
        y_key = round(w["doctop"] / 5) * 5
        if y_key not in filas:
            filas[y_key] = []
        filas[y_key].append(w)
    resultado = []
    for y_key in sorted(filas.keys()):
        fila = sorted(filas[y_key], key=lambda w: w["x0"])
        resultado.append(fila)
    return resultado

def _fila_a_texto(fila: list[dict]) -> str:
    """Convierte una fila de palabras en una línea de texto."""
    return " ".join(w["text"] for w in fila).strip()

def _es_fila_cabecera(texto: str, upper: str) -> bool:
    """Detecta si una fila es un encabezado que debe ignorarse."""
    if any(p in upper for p in ["VOCERO", "NOMBRE", "APELLIDO", "COMITE", "P/S", "C.I.", "TELEFONO", "VOTOS", "ELECTOS", "PRINCIPALES", "SUPLENTES"]):
        if any(q in upper for q in ["NOMBRE", "APELLIDO", "C.I.", "TELEFONO", "COMITE", "ELECTOS", "PRINCIPALES", "SUPLENTES", "VOCEROS"]):
            return True
    if upper.startswith("UNIDAD "):
        return True
    return False

def _es_fila_v_suelta(fila: list[dict]) -> bool:
    """Detecta si una fila es solo V- suelto."""
    texto = " ".join(w["text"] for w in fila).strip()
    return re.match(r'^V[-.\s]*$', texto, re.IGNORECASE) is not None

def _extraer_todos_voceros(texto_completo: str, palabras: list[dict]) -> list[dict]:
    """Extrae voceros usando coordenadas de palabras para agrupar filas correctamente."""
    texto_upper = texto_completo.upper()
    filas = _agrupar_por_filas(palabras)

    # Convertir filas a texto para búsqueda de secciones
    filas_texto = [_fila_a_texto(f).upper() for f in filas]

    todos = []

    for i, seccion in enumerate(SECCIONES):
        # Buscar inicio de sección en las filas
        inicio = -1
        for j, ft in enumerate(filas_texto):
            if seccion in ft:
                inicio = j
                break
        if inicio < 0:
            logger.debug("Sección no encontrada: %s", seccion)
            continue

        # Fin de sección = inicio de la siguiente
        fin = len(filas)
        if i + 1 < len(SECCIONES):
            for j in range(inicio + 1, len(filas_texto)):
                if SECCIONES[i + 1] in filas_texto[j]:
                    fin = j
                    break

        filas_seccion = filas[inicio:fin]
        logger.debug("Sección %s: filas %d-%d (%d filas)", seccion, inicio, fin, len(filas_seccion))

        # Determinar si tiene P/S
        tiene_ps = _detectar_ps_en_filas(filas_seccion)

        voceros = _procesar_filas_seccion(filas_seccion, seccion, tiene_ps)
        logger.debug("Sección %s: %d voceros extraídos", seccion, len(voceros))
        todos.extend(voceros)

    # Fallback
    if not todos:
        for f in filas:
            texto = _fila_a_texto(f)
            v = _parsear_sin_ps(texto, "")
            if v:
                todos.append(v)

    # Heredar vocería de fila anterior si está vacía
    ultima_voceria = ""
    for v in todos:
        if not v["voceria"]:
            v["voceria"] = ultima_voceria
        else:
            ultima_voceria = v["voceria"]

    # Limpiar vocerías que empiezan con "De "
    for v in todos:
        if v["voceria"].startswith("De "):
            v["voceria"] = v["voceria"][3:]

    # Eliminar duplicados por cédula (conservar la primera aparición)
    vistos = set()
    unicos = []
    for v in todos:
        if not v["cedula"]:
            unicos.append(v)
            continue
        if v["cedula"] not in vistos:
            vistos.add(v["cedula"])
            unicos.append(v)

    return unicos

def _detectar_ps_en_filas(filas: list[list[dict]]) -> bool:
    """Detecta si una sección tiene columna P/S."""
    for f in filas:
        for w in f:
            texto = w["text"].upper()
            if texto in ("P/S", "P /S", "P / S"):
                return True
    for f in filas:
        texto = _fila_a_texto(f).upper()
        if "P/S" in texto or "P /S" in texto:
            return True
    # Si alguna fila tiene P o S como palabra en la columna correcta
    ps_count = 0
    for f in filas:
        for w in f:
            if w["text"].upper() in ("P", "S") and abs(w["x0"] - 215) < 25:
                ps_count += 1
    return ps_count >= 2

def _procesar_filas_seccion(filas: list[list[dict]], nombre_seccion: str, tiene_ps: bool) -> list[dict]:
    """Procesa las filas de una sección y extrae voceros."""
    # Primera pasada: convertir filas a texto, saltando cabeceras
    filas_datos = []  # list of (fila, texto, doctop_medio)
    for f in filas:
        texto = _fila_a_texto(f)
        upper = texto.upper()
        if _es_fila_cabecera(texto, upper):
            continue
        if _es_fila_v_suelta(f):
            continue
        doctop = f[0]["doctop"] if f else 0
        filas_datos.append((f, texto, doctop))

    if not filas_datos:
        return []

    if not tiene_ps:
        # Sin P/S: cada fila es un vocero completo
        voceros = []
        for item in filas_datos:
            texto = item[1]
            v = _parsear_sin_ps(texto, nombre_seccion)
            if v:
                voceros.append(v)
        return voceros

    # Con P/S: agrupar filas multi-línea con merging contextual
    entradas_agrupadas = _agrupar_filas_con_ps(filas_datos)

    voceros = []
    for linea in entradas_agrupadas:
        if len(linea) < 8:
            continue
        v = _parsear_con_ps(linea)
        if v:
            voceros.append(v)

    return voceros

def _fila_tiene_ps(fila: list[dict]) -> bool:
    return any(w["text"].upper() in ("P", "S") and abs(w["x0"] - 215) < 25 for w in fila)

def _agrupar_filas_con_ps(filas_datos: list[tuple]) -> list[str]:
    """
    Agrupa filas de sección con P/S (Ejecutiva).
    filas_datos: list of (fila, texto, doctop)
    """
    # Paso 1: identificar filas P/S
    i_ps = []  # list of (idx, doctop)

    for i, item in enumerate(filas_datos):
        fila = item[0]
        if _fila_tiene_ps(fila):
            i_ps.append((i, item[2]))

    if not i_ps:
        return [item[1] for item in filas_datos]

    # Paso 2: preparar contenedores para cada P/S
    ps_indices = [ps_idx for ps_idx, _ in i_ps]
    ps_doctops = [ps_doctop for _, ps_doctop in i_ps]

    ps_info = {}
    for idx, _ in i_ps:
        ps_info[idx] = {
            "texto": filas_datos[idx][1],
            "fila": filas_datos[idx][0],
            "voceria_prefix": [],
            "voceria_suffix": [],
            "nombres": [],
            "ci": "",
        }

    # Asignar filas sin P/S a la P/S más cercana (por distancia Y real)
    for i, item in enumerate(filas_datos):
        if i in ps_info:
            continue
        fila, texto, doctop = item  # ahora 3 elementos
        if not texto.strip():
            continue

        # Distancia Y
        dists = [abs(doctop - ps_doctop) for ps_doctop in ps_doctops]
        if not dists:
            continue
        min_dist = min(dists)
        candidates = [ps_indices[k] for k, d in enumerate(dists) if d == min_dist]

        # Clasificar la fila
        # Tiene CI suelta? (dígitos a x0≈425)
        ci_candidates = [w for w in fila if 400 < w["x0"] < 450]
        ci_words_set = set(w["text"] for w in ci_candidates if w["text"].isdigit())
        es_solo_ci = all(
            (410 < w["x0"] < 440 and w["text"].isdigit()) or w["text"].upper() == "V-"
            for w in fila
        )

        ci_parts = [w for w in ci_candidates if w["text"].isdigit()]

        voceria_parts = [w for w in fila if w["x0"] < 200 and w["text"].upper() != "V-"]
        nombre_parts = [
            w for w in fila
            if w["x0"] > 230
            and w["text"].upper() != "V-"
            and w["text"] not in ci_words_set
        ]

        # Resolver empate de distancia al P/S más cercano
        if len(candidates) > 1:
            # Nombre puro → siguiente P/S (el de abajo)
            # CI puro → P/S anterior (el de arriba)
            # Vocería con CI → P/S anterior (sufijo + CI típico)
            # Vocería sola → siguiente P/S (prefijo)
            if nombre_parts and not ci_parts and not voceria_parts:
                nearest = max(candidates)
            elif ci_parts and (voceria_parts or not nombre_parts):
                nearest = min(candidates)
            elif voceria_parts and not ci_parts and not nombre_parts:
                nearest = max(candidates)
            else:
                nearest = max(candidates)
        else:
            nearest = candidates[0]

        if ci_parts:
            ps_info[nearest]["ci"] = "V-" + " ".join(w["text"] for w in ci_parts)

        if voceria_parts and not _fila_tiene_ps(fila):
            voc_text = " ".join(w["text"] for w in voceria_parts)
            if i < nearest:
                ps_info[nearest]["voceria_prefix"].append(voc_text)
            else:
                ps_info[nearest]["voceria_suffix"].append(voc_text)

        if nombre_parts and not _fila_tiene_ps(fila):
            nom_text = " ".join(w["text"] for w in nombre_parts)
            ps_info[nearest]["nombres"].append(nom_text)

    # Paso 3: reconstruir entradas completas
    entradas = []
    for idx in sorted(ps_info.keys()):
        info = ps_info[idx]
        fila = info["fila"]
        texto = info["texto"]

        # Extraer vocería y datos del texto P/S
        ps_idx_w = None
        for j, w in enumerate(fila):
            if w["text"].upper() in ("P", "S") and abs(w["x0"] - 215) < 25:
                ps_idx_w = j
                break
        if ps_idx_w is None:
            entradas.append(texto)
            continue

        voceria = " ".join(w["text"] for w in fila[:ps_idx_w])
        ps = fila[ps_idx_w]["text"].upper()
        datos = " ".join(w["text"] for w in fila[ps_idx_w + 1:])

        # Vocería prefix + suffix
        voc_pre = " ".join(info["voceria_prefix"])
        voc_suf = " ".join(info["voceria_suffix"])
        voceria_completa = " ".join(p for p in [voc_pre, voceria, voc_suf] if p)

        # Nombres
        nombre_completo = " ".join(info["nombres"])

        # CI
        ci = info["ci"]

        # Reconstruir entrada
        if nombre_completo:
            entrada = f"{voceria_completa} {ps} {nombre_completo} {datos}"
        else:
            entrada = f"{voceria_completa} {ps} {datos}"

        if ci and ci not in entrada:
            entrada += " " + ci

        entradas.append(entrada)

    # Paso 4: añadir filas sin P/S que no se asignaron (fallback)
    for i, item in enumerate(filas_datos):
        if i not in ps_info:
            fila, texto, _ = item
            if texto.strip():
                ci_parts = [w["text"] for w in fila if 410 < w["x0"] < 440 and w["text"].isdigit()]
                if ci_parts and not any(w["x0"] < 400 for w in fila):
                    continue
                entradas.append(texto)

    return entradas

def _parsear_con_ps(linea: str) -> dict | None:
    """Formato: Vocería P/S Nombre [V-Cédula] Teléfono Votos"""
    resto = linea.strip()

    # Extraer tipo (P/S como palabra independiente)
    m_ps = re.search(r'\b([PS])\s+(.+)$', resto, re.IGNORECASE)
    if not m_ps:
        return None

    tipo = "Principal" if m_ps.group(1).upper() == "P" else "Suplente"
    voceria = resto[:m_ps.start()].strip()
    resto = m_ps.group(2).strip()

    # Extraer cédula y teléfono (pueden venir corridos: V-91437364141773043)
    cedula = ""
    telefono = ""

    # Buscar cadena completa de dígitos con prefijo V/J/E/P
    m_concat = re.search(r'[VJEP][-.\s]*(\d{5,20})', resto, re.IGNORECASE)
    if m_concat:
        digitos = m_concat.group(1)
        nombre_resto = resto[:m_concat.start()].strip()
        resto = nombre_resto + " " + resto[m_concat.end():].strip()
        resto = resto.strip()
        # Buscar prefijo de operadora dentro de los dígitos
        m_op = re.search(r'(414|416|424|412|426|422)', digitos)
        if m_op:
            cedula = _limpiar_cedula(digitos[:m_op.start()])
            telefono = digitos[m_op.start():]
        else:
            cedula = _limpiar_cedula(digitos[:8]) if len(digitos) > 8 else _limpiar_cedula(digitos)
            telefono = digitos[8:] if len(digitos) > 8 else ""
    else:
        # Cédula suelta
        m_ci = re.search(r'\b(\d{7,8})\b', resto)
        if m_ci:
            cedula = m_ci.group(1)
            resto = (resto[:m_ci.start()] + resto[m_ci.end():]).strip()

    # Extraer votos (último número 1-4 dígitos)
    votos = ""
    m_votos = re.search(r'(\d{1,4})\s*$', resto)
    if m_votos:
        votos = m_votos.group(1)
        resto = resto[:m_votos.start()].strip()

    # Extraer teléfono suelto (10 dígitos)
    if not telefono:
        m_tel = re.search(r'\b(\d{10})\b', resto)
        if m_tel:
            telefono = m_tel.group(1)
            resto = (resto[:m_tel.start()] + resto[m_tel.end():]).strip()

    nombre = _limpiar_nombre(re.sub(r'\s+', ' ', resto).strip())

    if not nombre and not cedula:
        return None

    return {
        "nombre": nombre, "cedula": cedula,
        "voceria": voceria.strip().title(), "tipo": tipo,
        "telefono": telefono, "votos": votos
    }

def _parsear_sin_ps(linea: str, nombre_seccion: str) -> dict | None:
    """Formato: Nombre V-Cédula Teléfono Votos (sin vocería ni P/S)"""
    resto = linea.strip()

    # Extraer vocería del nombre de sección
    # Nombre amigable: "UNIDAD ADMINISTRATIVA Y FINANCIERA" → "Administrativa Y Financiera"
    voceria_base = nombre_seccion.replace("UNIDAD ", "").replace(" DE ", " De ").replace("VOCEROS ", "").strip().title()

    # Extraer cédula y teléfono (pueden venir corridos)
    cedula = ""
    telefono = ""

    m_concat = re.search(r'[VJEP][-.\s]*(\d{5,20})', resto, re.IGNORECASE)
    if m_concat:
        digitos = m_concat.group(1)
        resto = resto[:m_concat.start()].strip() + " " + resto[m_concat.end():].strip()
        resto = resto.strip()
        m_op = re.search(r'(414|416|424|412|426|422)', digitos)
        if m_op:
            cedula = _limpiar_cedula(digitos[:m_op.start()])
            telefono = digitos[m_op.start():]
        else:
            cedula = _limpiar_cedula(digitos[:8]) if len(digitos) > 8 else _limpiar_cedula(digitos)
            telefono = digitos[8:] if len(digitos) > 8 else ""
    else:
        m_ci = re.search(r'\b(\d{7,8})\b', resto)
        if m_ci:
            cedula = m_ci.group(1)
            resto = (resto[:m_ci.start()] + resto[m_ci.end():]).strip()

    if not cedula:
        return None

    # Extraer votos
    votos = ""
    m_votos = re.search(r'(\d{1,4})\s*$', resto)
    if m_votos:
        votos = m_votos.group(1)
        resto = resto[:m_votos.start()].strip()

    # Extraer teléfono
    telefono = ""
    m_tel = re.search(r'\b(\d{9,12})\b', resto)
    if m_tel:
        telefono = _limpiar_telefono(m_tel.group(1))
        resto = (resto[:m_tel.start()] + resto[m_tel.end():]).strip()

    nombre = _limpiar_nombre(re.sub(r'\s+', ' ', resto).strip())

    return {
        "nombre": nombre, "cedula": cedula,
        "voceria": voceria_base, "tipo": "Principal",
        "telefono": telefono, "votos": votos
    }

def _extraer_datos_con_ocr_zhipu(pdf_path: Path) -> dict:
    import fitz  # PyMuPDF
    import base64
    import httpx
    import json
    from backend.config import ZHIPU_API_KEY
    
    if not ZHIPU_API_KEY:
        logger.error("No hay ZHIPU_API_KEY configurada para usar el OCR visual.")
        return {"codigo_registro": "", "fecha_acta": "", "nombre_consejo": "", "sector": "", "voceros": []}

    try:
        # Extraer la primera página como imagen para el OCR rápido
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        pix = page.get_pixmap()
        img_bytes = pix.tobytes("jpeg")
        base64_image = base64.b64encode(img_bytes).decode("utf-8")
        doc.close()
    except Exception as e:
        logger.error(f"Error convirtiendo PDF a imagen para OCR: {e}")
        return {"codigo_registro": "", "fecha_acta": "", "nombre_consejo": "", "sector": "", "voceros": []}

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt_ocr = """
    Extrae la siguiente información de esta Acta de Asamblea. Devuelve ÚNICAMENTE un JSON válido con esta estructura exacta, sin texto adicional:
    {
        "codigo_registro": "",
        "fecha_acta": "",
        "nombre_consejo": "",
        "sector": "",
        "voceros": [
            {
                "nombre": "",
                "cedula": "",
                "voceria": "",
                "tipo": "Principal o Suplente",
                "telefono": "",
                "votos": ""
            }
        ]
    }
    """
    
    data = {
        "model": "glm-4v-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_ocr},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "temperature": 0.1
    }
    
    with httpx.Client(timeout=60.0) as client:
        try:
            response = client.post(url, headers=headers, json=data)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                content = content.replace("```json", "").replace("```", "").strip()
                return json.loads(content)
            else:
                logger.error(f"OCR Zhipu Error: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Exception OCR Zhipu: {str(e)}")
            
    return {"codigo_registro": "", "fecha_acta": "", "nombre_consejo": "", "sector": "", "voceros": []}


