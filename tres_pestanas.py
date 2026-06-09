# Script para inyectar las 3 pestañas nuevas en index.html
# Se corre desde la raíz del proyecto: python tres_pestanas.py

from pathlib import Path
import re

path = Path('frontend/index.html')
txt = path.read_text(encoding='utf-8')

# ── 1. Agregar pestañas a la nav ──────────────────────────────────────────
old_nav = '''  <div class="poder-tab" onclick="switchPoder('judicial', this)">⚖️ Judicial <span class="cnt" id="cnt-jud">—</span></div>
</nav>'''

new_nav = '''  <div class="poder-tab" onclick="switchPoder('judicial', this)">⚖️ Judicial <span class="cnt" id="cnt-jud">—</span></div>
  <div class="poder-tab" onclick="switchPanel('manual', this)" style="margin-left:auto">📖 Manual</div>
  <div class="poder-tab" onclick="switchPanel('indicadores', this)">🔬 Indicadores</div>
  <div class="poder-tab" onclick="switchPanel('autor', this)">👤 Autor</div>
</nav>'''

txt = txt.replace(old_nav, new_nav)

# ── 2. Insertar los 3 paneles antes del cierre de <main> ──────────────────
panels = '''
  <!-- ═══ PANEL MANUAL ═══ -->
  <div class="poder-panel" id="panel-manual">
    <div class="card" style="max-width:860px;margin:0 auto">
      <div class="card-title">📖 Manual de uso — Monitor DDJJ</div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px">

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#7aaeff;margin-bottom:10px">🔍 Buscar y filtrar</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            Usá la barra de búsqueda para encontrar un funcionario por nombre u organismo.
            Los filtros de nivel (CRÍTICO / ALTO / MEDIO / BAJO) y año permiten acotar los resultados.
            El ranking muestra hasta 200 registros — los más riesgosos primero.
          </p>
        </div>

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#00d4aa;margin-bottom:10px">💰 Columnas de patrimonio</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            <strong style="color:#c8d0e0">Bienes finales (ARS)</strong> — valor declarado en la DDJJ original, en pesos argentinos.<br>
            <strong style="color:#c8d0e0">Equiv. (USD)</strong> — convertido al TC oficial BNA de diciembre del año declarado
            (2022: $177 · 2023: $808 · 2024: $1.045).
          </p>
        </div>

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#ff6b35;margin-bottom:10px">⚠️ Columna Score y Nivel</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            El <strong style="color:#c8d0e0">score de riesgo</strong> (0–100) es un índice algorítmico basado en tres dimensiones:
            IVPI (incremento patrimonial vs ingresos), opacidad (efectivo/total) y fuga (activos exterior).
            <br><br>
            <span style="color:#e63946">■ CRÍTICO</span> ≥75 &nbsp;
            <span style="color:#ff6b35">■ ALTO</span> ≥50 &nbsp;
            <span style="color:#ffd060">■ MEDIO</span> ≥25 &nbsp;
            <span style="color:#2ec27e">■ BAJO</span> &lt;25
          </p>
        </div>

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#ffd060;margin-bottom:10px">📊 IVPI — Índice de Variación Patrimonial</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            IVPI = Δpatrimonio USD / ingresos USD declarados.<br>
            Un IVPI de <strong style="color:#c8d0e0">2×</strong> significa que el patrimonio creció el doble de lo que el funcionario declaró como ingresos.
            <br><br>
            <span style="color:#e63946">ROJA</span> &gt;3× &nbsp;
            <span style="color:#ffd060">AMARILLA</span> &gt;1.5× &nbsp;
            <span style="color:#2ec27e">VERDE</span> ≤1.5×<br>
            <span style="color:#5a6480;font-size:.7rem">No implica ilicitud — solo señal estadística para priorizar revisión.</span>
          </p>
        </div>

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#a78bfa;margin-bottom:10px">👤 Ficha individual (Ver →)</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            Al hacer clic en <strong style="color:#c8d0e0">Ver →</strong> se abre la ficha completa con:
            patrimonio en ARS y USD, variación vs año anterior, ingresos, IVPI, gráfico de evolución histórica
            (2022–2024) e indicadores internacionales (FATF · WB · TI · OCDE).
          </p>
        </div>

        <div style="background:#0f1620;border:1px solid #1e2535;border-radius:8px;padding:18px">
          <div style="font-size:.8rem;font-weight:700;color:#60a5fa;margin-bottom:10px">🗂️ Fuentes y limitaciones</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7">
            Datos de <strong style="color:#c8d0e0">datos.jus.gob.ar</strong> — Oficina Anticorrupción (OA).
            Años disponibles: 2022, 2023 y 2024. Datos 2025 se publican en septiembre/octubre 2026.<br>
            Contrataciones públicas: sin datos (DNS no resuelve en el período de análisis).
          </p>
        </div>

      </div>

      <div style="background:#090d14;border:1px solid #1a2535;border-radius:6px;padding:14px 18px;font-size:.72rem;color:#4a5a70;line-height:1.7">
        ⚠️ <strong style="color:#5a7a90">Herramienta académica.</strong>
        Los scores son indicadores algorítmicos de riesgo — no implican juicio legal ni determinación de responsabilidad.
        Metodología basada en Monteverde (2019) · <em>Journal of Financial Crime</em> · Emerald Publishing.
        Datos amparados por Ley 27.275 de Acceso a la Información Pública.
      </div>
    </div>
  </div>

  <!-- ═══ PANEL INDICADORES INTERNACIONALES ═══ -->
  <div class="poder-panel" id="panel-indicadores">
    <div class="card" style="max-width:900px;margin:0 auto">
      <div class="card-title">🔬 Indicadores Internacionales — FATF · World Bank · TI · OCDE</div>

      <p style="font-size:.78rem;color:#8090b0;line-height:1.7;margin-bottom:20px">
        Cada DDJJ es evaluada contra 12 indicadores de cuatro marcos internacionales de integridad pública.
        El score se renormaliza al 100% según los indicadores con datos disponibles en los CSV públicos de la OA.
        <strong style="color:#7aaeff">Argentina: CPI-TI 2023 = 38/100 · WB CCI percentil 43.8 · salió de lista gris FATF en 2023.</strong>
      </p>

      <!-- FATF -->
      <div style="margin-bottom:20px">
        <div style="font-size:.75rem;font-weight:700;color:#e63946;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:8px">
          <span style="background:#3a0f0f;border:1px solid #5a1f1f;padding:2px 8px;border-radius:4px">FATF / GAFI</span>
          Grupo A — Recomendaciones R.12 · R.24 · R.25
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">A1 · PEP Screening <span style="color:#5a6480;font-weight:400">(peso 8%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Identifica Personas Expuestas Políticamente por cargo (ministro, juez, senador, etc.). Score 30 si el cargo es PEP según R.12.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">A2 · Beneficial Ownership <span style="color:#5a6480;font-weight:400">(peso 7%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Detecta participaciones societarias (R.24/25). Score 20 si tiene sociedades, 35 si están en jurisdicciones de lista gris/negra FATF 2024.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">A3 · Cash Ratio &gt;30% <span style="color:#5a6480;font-weight:400">(peso 8%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Umbral ALD: efectivo &gt;30% del patrimonio es señal de alerta. Sin datos en CSV público de OA — score 0 por ahora.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">A4 · Jurisdicciones de riesgo <span style="color:#5a6480;font-weight:400">(peso 7%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Activos en países de lista negra FATF (Corea del Norte, Irán, Myanmar) = 40 pts. Lista gris = 20 pts.</div>
          </div>
        </div>
      </div>

      <!-- World Bank -->
      <div style="margin-bottom:20px">
        <div style="font-size:.75rem;font-weight:700;color:#3b6fff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:8px">
          <span style="background:#0f1e40;border:1px solid #1a3060;padding:2px 8px;border-radius:4px">WORLD BANK</span>
          Grupo B — WGI Control of Corruption 2024
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">B1 · Percentil pares LAC <span style="color:#5a6480;font-weight:400">(peso 10%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Compara patrimonio con pares del mismo cargo. P95 = 35 pts · P80 = 20 pts. Argentina percentil 43.8 vs LAC 49.3.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">B2 · Brecha salario &gt;10× <span style="color:#5a6480;font-weight:400">(peso 10%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Patrimonio &gt;10× el ingreso acumulado del mandato (4 años default). Umbral WGI 2024 para funcionarios LAC.</div>
          </div>
        </div>
      </div>

      <!-- TI -->
      <div style="margin-bottom:20px">
        <div style="font-size:.75rem;font-weight:700;color:#ffd060;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:8px">
          <span style="background:#2e2200;border:1px solid #4a3800;padding:2px 8px;border-radius:4px">TRANSPARENCY INTL</span>
          Grupo C — CPI 2023 (Argentina: 38/100)
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">C1 · Velocidad de acumulación <span style="color:#5a6480;font-weight:400">(peso 10%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">IVPI vs benchmark CPI&lt;40: bm=1.2×/año. Score 10 si &gt;bm · 20 si &gt;2×bm · 30 si &gt;3×bm.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">C2 · Sector de riesgo TI <span style="color:#5a6480;font-weight:400">(peso 5%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Organismo en sector de alto riesgo TI: obra pública, contratos, licitaciones, energía, minería, agro. Score 15.</div>
          </div>
        </div>
      </div>

      <!-- OCDE -->
      <div style="margin-bottom:20px">
        <div style="font-size:.75rem;font-weight:700;color:#00d4aa;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:8px">
          <span style="background:#0f2e1f;border:1px solid #1a4a30;padding:2px 8px;border-radius:4px">OCDE</span>
          Grupo D — Recomendación Integridad Pública 2017
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">D1 · Completitud declaratoria <span style="color:#5a6480;font-weight:400">(peso 5%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Pilar 5 OCDE: campos obligatorios declarados (inmuebles, vehículos, depósitos, efectivo, sociedades, deudas, ingresos).</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">D2 · Conflicto de interés <span style="color:#5a6480;font-weight:400">(peso 13%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Cruza con alertas_conflicto.csv (Fase 2). Alerta roja = 40 pts · alerta amarilla = 20 pts.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">D3 · Puerta giratoria <span style="color:#5a6480;font-weight:400">(peso 10%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Paso sector público↔privado en &lt;365 días (alertas_puertas_giratorias.csv). Score 30 si detectado.</div>
          </div>
          <div style="background:#0f1620;border:1px solid #1e2535;border-radius:6px;padding:12px 14px">
            <div style="font-size:.75rem;font-weight:600;color:#c8d0e0;margin-bottom:4px">D4 · Evolución patrimonial <span style="color:#5a6480;font-weight:400">(peso 7%)</span></div>
            <div style="font-size:.72rem;color:#8090b0;line-height:1.6">Ratio acumulado vs umbral OCDE 1.5×/año de mandato. Score 10/20/35 según supere 1×/1.5×/2× el umbral.</div>
          </div>
        </div>
      </div>

      <div style="background:#090d14;border:1px solid #1a3a2a;border-radius:6px;padding:12px 16px;font-size:.72rem;color:#4a6a5a;line-height:1.7">
        📌 <strong style="color:#5a9a7a">Renormalización:</strong>
        A3 (efectivo), A4 (jurisdicciones), D2 (conflicto) y D3 (puertas) tienen score 0 por falta de datos en los CSV públicos de la OA.
        El score internacional se renormaliza sobre los pesos disponibles (actualmente 50/100) para que el resultado sea comparable.
        Fuentes: <a href="https://www.fatf-gafi.org" target="_blank" style="color:#7aaeff">FATF</a> ·
        <a href="https://info.worldbank.org/governance/wgi/" target="_blank" style="color:#7aaeff">WB WGI</a> ·
        <a href="https://www.transparency.org/en/cpi/2023" target="_blank" style="color:#7aaeff">TI CPI</a> ·
        <a href="https://www.oecd.org/gov/ethics/" target="_blank" style="color:#7aaeff">OCDE PAI</a>
      </div>
    </div>
  </div>

  <!-- ═══ PANEL AUTOR Y DONACIÓN ═══ -->
  <div class="poder-panel" id="panel-autor">
    <div style="max-width:860px;margin:0 auto">

      <!-- Perfil -->
      <div style="background:#161b27;border:1px solid #1e2535;border-radius:12px;padding:28px;margin-bottom:20px;display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:start">
        <div style="width:90px;height:90px;border-radius:50%;background:linear-gradient(135deg,#1e3a8a,#3b6fff);display:flex;align-items:center;justify-content:center;font-size:2.2rem;flex-shrink:0">👨‍🎓</div>
        <div>
          <div style="font-size:1.2rem;font-weight:700;color:#e8edf5;margin-bottom:4px">Ph.D. Vicente Humberto Monteverde</div>
          <div style="font-size:.78rem;color:#7aaeff;margin-bottom:12px;font-family:var(--mono)">Economía Política · Fenómenos Corruptivos · Algoritmos XAI</div>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7;margin-bottom:12px">
            Investigador en economía política y fenómenos de corrupción. Doctor en Ciencias Económicas.
            Autor de la teoría de <strong style="color:#c8d0e0">Transferencia Regresiva de Ingresos</strong> y desarrollador del
            algoritmo XAI aplicado al análisis de contrataciones públicas.
          </p>
          <p style="font-size:.78rem;color:#8090b0;line-height:1.7;margin-bottom:16px">
            Publicaciones en <strong style="color:#c8d0e0">Journal of Financial Crime</strong> (Emerald Publishing) y Dialnet.
            Asesor en transparencia y auditoría algorítmica del gasto público.
          </p>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <a href="mailto:vhmonte@retina.ar" style="display:inline-flex;align-items:center;gap:6px;background:#0f1e40;border:1px solid #1a3060;color:#7aaeff;padding:6px 14px;border-radius:6px;font-size:.75rem;text-decoration:none;font-family:var(--mono)">✉️ vhmonte@retina.ar</a>
            <a href="mailto:viny01958@gmail.com" style="display:inline-flex;align-items:center;gap:6px;background:#0f1e40;border:1px solid #1a3060;color:#7aaeff;padding:6px 14px;border-radius:6px;font-size:.75rem;text-decoration:none;font-family:var(--mono)">✉️ viny01958@gmail.com</a>
            <a href="https://github.com/Viny2030/decla" target="_blank" style="display:inline-flex;align-items:center;gap:6px;background:#0f1620;border:1px solid #1e2535;color:#8090b0;padding:6px 14px;border-radius:6px;font-size:.75rem;text-decoration:none;font-family:var(--mono)">⌥ github.com/Viny2030/decla</a>
          </div>
        </div>
      </div>

      <!-- Donaciones -->
      <div style="background:#161b27;border:1px solid #1e2535;border-radius:12px;padding:24px">
        <div style="text-align:center;margin-bottom:20px">
          <div style="font-size:1rem;font-weight:700;color:#e8edf5;margin-bottom:4px">💛 Apoyar este proyecto — Donaciones voluntarias</div>
          <div style="font-size:.75rem;color:#5a6480">Si este proyecto te resulta útil, podés apoyarlo con una donación voluntaria.</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px">

          <!-- ARS -->
          <div style="background:#0f1620;border:1px solid #1a3060;border-radius:8px;padding:16px">
            <div style="font-size:.65rem;font-weight:700;color:#7aaeff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">🇦🇷 Argentina · Pesos (ARS)</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">TIPO</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Caja de Ahorro</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CBU</div>
            <div style="font-size:.72rem;color:#7aaeff;font-family:var(--mono);margin-bottom:8px">0140005203400552652310</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">ALIAS</div>
            <div style="font-size:.75rem;color:#00d4aa;font-family:var(--mono);margin-bottom:8px">ALGORIT.MONTE.PESOS</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">TITULAR</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Vicente Humberto Monteverde</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CUIL/CUIT</div>
            <div style="font-size:.75rem;color:#c8d0e0;font-family:var(--mono)">20-12034411-1</div>
          </div>

          <!-- USD -->
          <div style="background:#0f1620;border:1px solid #1a3060;border-radius:8px;padding:16px">
            <div style="font-size:.65rem;font-weight:700;color:#7aaeff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">🇦🇷 Argentina · Dólares (USD)</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">TIPO</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Caja de Ahorro Dólares</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CBU</div>
            <div style="font-size:.72rem;color:#7aaeff;font-family:var(--mono);margin-bottom:8px">0140005204400550329709</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">ALIAS</div>
            <div style="font-size:.75rem;color:#00d4aa;font-family:var(--mono);margin-bottom:8px">ALGO.MONTE.DOLARES</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">TITULAR</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Vicente Humberto Monteverde</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CUIL/CUIT</div>
            <div style="font-size:.75rem;color:#c8d0e0;font-family:var(--mono)">20-12034411-1</div>
          </div>

          <!-- Wire -->
          <div style="background:#0f1620;border:1px solid #1a4a30;border-radius:8px;padding:16px">
            <div style="font-size:.65rem;font-weight:700;color:#00d4aa;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">🌐 Desde el Exterior (USD Wire)</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">BANCO</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Banco Santander Rio</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">BENEFICIARIO</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Vicente Humberto Monteverde</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">DIRECCIÓN</div>
            <div style="font-size:.75rem;color:#c8d0e0;margin-bottom:8px">Av. Directorio 3024 PB DTO 04</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CUENTA USD</div>
            <div style="font-size:.72rem;color:#7aaeff;font-family:var(--mono);margin-bottom:8px">005200183500</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">SWIFT / BIC</div>
            <div style="font-size:.75rem;color:#00d4aa;font-family:var(--mono);margin-bottom:8px">BSCHUYMM</div>
            <div style="font-size:.7rem;color:#5a6480;margin-bottom:2px">CUIT</div>
            <div style="font-size:.75rem;color:#c8d0e0;font-family:var(--mono)">20-12034411-1</div>
          </div>

        </div>
      </div>

    </div>
  </div>

'''

# ── 3. Insertar antes de </main> ──────────────────────────────────────────
txt = txt.replace('\n</main>', panels + '\n</main>')

# ── 4. Agregar función switchPanel al JS ──────────────────────────────────
js_patch = '''
// ── Switch paneles estáticos (Manual / Indicadores / Autor) ───────────────
function switchPanel(panel, el) {
  document.querySelectorAll('.poder-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.poder-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const p = document.getElementById('panel-' + panel);
  if (p) p.classList.add('active');
}
'''

txt = txt.replace('// ── Switch de panel de poder', js_patch + '\n// ── Switch de panel de poder')

path.write_text(txt, encoding='utf-8')
print("✅ 3 pestañas insertadas en index.html")