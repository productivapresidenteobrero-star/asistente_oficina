import re

def extract_main_content(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        html = f.read()
    # Extraer el contenido dentro de <main>...</main>
    match = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

def build_index():
    # 1. Leer el Dashboard para sacar la cabecera (head, nav, etc)
    with open('Dashboard.html', 'r', encoding='utf-8') as f:
        dash_html = f.read()
    
    # Vamos a crear la estructura base
    # Reemplazamos <main ...>...</main> con un <main ...> que tenga las secciones
    
    main_start_match = re.search(r'(<main[^>]*>)', dash_html)
    main_end_idx = dash_html.find('</main>')
    
    if not main_start_match or main_end_idx == -1:
        print("Error: No se encontro <main> en Dashboard.html")
        return

    main_start = main_start_match.group(1)
    
    head_and_header = dash_html[:main_start_match.end()]
    footer = dash_html[main_end_idx:]

    # Extraer los contenidos
    dashboard_content = extract_main_content('Dashboard.html')
    directorio_content = extract_main_content('Directorio de Vocerias.html')
    consultas_content = extract_main_content('Consultas populares.html')

    # Reemplazamos las clases para que <main> no restrinja el ancho (Dashboard tenia max-w-md mx-auto que no aplica al resto)
    # Haremos que las sections controlen su propio ancho, o dejaremos el main general.
    # El dashboard tiene <main class="px-md pt-lg flex flex-col gap-lg max-w-md mx-auto">
    # El directorio tiene <main class="flex-1 flex flex-col h-screen overflow-y-auto bg-background relative pb-20 lg:pb-0">
    # Las consultas tiene <main class="lg:ml-72 pt-20 lg:pt-0 p-md lg:p-xxl min-h-screen">
    
    # Usaremos el de Consultas / Directorio como base porque tiene el Sidebar layout en Desktop
    with open('Consultas populares.html', 'r', encoding='utf-8') as f:
        consultas_html = f.read()
    
    head_match = re.search(r'(<head>.*?</head>)', consultas_html, re.DOTALL)
    body_start = re.search(r'(<body[^>]*>)', consultas_html).group(1)
    
    sidebar = re.search(r'(<aside class="hidden lg:flex.*?</aside>)', consultas_html, re.DOTALL).group(1)
    topbar_mobile = re.search(r'(<header class="lg:hidden.*?</header>)', consultas_html, re.DOTALL).group(1)
    bottom_nav = re.search(r'(<nav class="lg:hidden fixed bottom-0.*?</nav>)', consultas_html, re.DOTALL).group(1)
    fab = re.search(r'(<button class="lg:hidden fixed bottom-24.*?</button>)', consultas_html, re.DOTALL).group(1)
    scripts = re.search(r'(<script>.*?</script>\s*</body>)', consultas_html, re.DOTALL).group(1)
    
    # Construir main unificado
    unified_main_start = '<main class="lg:ml-72 pt-20 lg:pt-0 p-md lg:p-xxl min-h-screen">'
    
    # Sections (ocultas por defecto excepto dashboard)
    # Clases para tab-pane: oculto por defecto (hidden), cuando active (block)
    # Haremos unas clases simples en style
    extra_style = """
    <style>
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }
    </style>
    """
    
    head_content = head_match.group(1).replace('</head>', extra_style + '</head>')
    
    # Modificar enlaces del sidebar para que actuen como tabs
    # Reemplazamos los href="#" por data-tab="dashboard", etc.
    sidebar = sidebar.replace('href="#"', 'href="#" class="nav-item"')
    # Agregamos los data-tab manualmente a los a
    sidebar = sidebar.replace('<span class="material-symbols-outlined">grid_view</span>', '<span class="material-symbols-outlined">grid_view</span>').replace('<span class="text-body-md font-body-md">Dashboard</span>', '<span class="text-body-md font-body-md">Dashboard</span>')
    # Let's just do a simple replacement for data-tabs
    sidebar = re.sub(r'<a(.*?)<span.*?grid_view', r'<a\1 data-tab="dashboard"<span class="material-symbols-outlined">grid_view', sidebar)
    sidebar = re.sub(r'<a(.*?)<span.*?badge', r'<a\1 data-tab="padron"<span class="material-symbols-outlined">badge', sidebar)
    sidebar = re.sub(r'<a(.*?)<span.*?how_to_vote', r'<a\1 data-tab="consultas"<span class="material-symbols-outlined">how_to_vote', sidebar)
    sidebar = re.sub(r'<a(.*?)<span.*?history_edu', r'<a\1 data-tab="bitacora"<span class="material-symbols-outlined">history_edu', sidebar)
    sidebar = re.sub(r'<a(.*?)<span.*?analytics', r'<a\1 data-tab="informes"<span class="material-symbols-outlined">analytics', sidebar)
    sidebar = re.sub(r'<a(.*?)<span.*?search', r'<a\1 data-tab="archivos"<span class="material-symbols-outlined">search', sidebar)

    # Same for bottom_nav
    bottom_nav = re.sub(r'<a(.*?)<span.*?dashboard', r'<a\1 data-tab="dashboard"<span class="material-symbols-outlined">dashboard', bottom_nav)
    bottom_nav = re.sub(r'<a(.*?)<span.*?group', r'<a\1 data-tab="padron"<span class="material-symbols-outlined">group', bottom_nav)
    bottom_nav = re.sub(r'<a(.*?)<span.*?poll', r'<a\1 data-tab="consultas"<span class="material-symbols-outlined">poll', bottom_nav)
    bottom_nav = re.sub(r'<a(.*?)<span.*?folder_open', r'<a\1 data-tab="archivos"<span class="material-symbols-outlined">folder_open', bottom_nav)

    sections = f'''
    <section id="tab-dashboard" class="tab-pane active">
        {dashboard_content}
    </section>
    
    <section id="tab-padron" class="tab-pane">
        {directorio_content}
    </section>
    
    <section id="tab-consultas" class="tab-pane">
        {consultas_content}
    </section>
    
    <section id="tab-archivos" class="tab-pane">
        <div class="mb-xl">
            <h1 class="text-headline-lg font-headline-lg text-on-surface mb-xs">Buscador y Archivos (Proximamente)</h1>
        </div>
    </section>

    <section id="tab-bitacora" class="tab-pane">
        <div class="mb-xl">
            <h1 class="text-headline-lg font-headline-lg text-on-surface mb-xs">Bitácora (Proximamente)</h1>
        </div>
    </section>

    <section id="tab-informes" class="tab-pane">
        <div class="mb-xl">
            <h1 class="text-headline-lg font-headline-lg text-on-surface mb-xs">Informes (Proximamente)</h1>
        </div>
    </section>
    '''

    unified_html = f'''<!DOCTYPE html>
<html class="light" lang="es">
{head_content}
{body_start}
    {sidebar}
    {topbar_mobile}
    
    {unified_main_start}
        {sections}
    </main>
    
    {bottom_nav}
    {fab}
    
    <script src="/frontend/app.js"></script>
{scripts}
</html>
'''

    with open('frontend/index.html', 'w', encoding='utf-8') as f:
        f.write(unified_html)
    print("frontend/index.html unificado generado con exito.")

build_index()
