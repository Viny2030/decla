/* frescura.js — ficha "De dónde salen estos datos" (formato común del ecosistema).
 * Uso: <div id="frescura-ficha" data-api="/api/frescura"></div>
 *      <script src="frescura.js" defer></script>
 * Lee el endpoint y muestra, por dato: fuente, período que cubre, última carga
 * y estado. Si el endpoint no responde, no muestra nada (no inventa fechas). */
(function () {
  const ESTADOS = {
    al_dia:             { txt: 'Al día',               color: '#15803d', bg: '#dcfce7' },
    atrasado_contenido: { txt: 'La fuente no publicó datos nuevos', color: '#92400e', bg: '#fef3c7' },
    atrasado_tecnico:   { txt: 'Falló la actualización', color: '#b91c1c', bg: '#fee2e2' },
  };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fecha = iso => {
    if (!iso) return '—';
    const d = new Date(iso.length <= 10 ? iso + 'T12:00:00' : iso);
    return isNaN(d) ? esc(iso) : d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  };
  async function montar(el) {
    let data;
    try {
      const r = await fetch(el.dataset.api || '/api/frescura', { headers: { Accept: 'application/json' } });
      if (!r.ok) return;
      data = await r.json();
    } catch (e) { return; }
    if (!data || !Array.isArray(data.datos)) return;
    const res = data.resumen || {};
    const alertas = (res.atrasado_tecnico || 0) + (res.atrasado_contenido || 0);
    const filas = data.datos.map(d => {
      const e = ESTADOS[d.estado] || ESTADOS.al_dia;
      const fuente = d.fuente_url ? `<a href="${esc(d.fuente_url)}" target="_blank" rel="noopener">${esc(d.fuente)}</a>` : esc(d.fuente);
      return `<tr>
        <td><strong>${esc(d.dato)}</strong>${d.nota ? `<div class="fr-nota">${esc(d.nota)}</div>` : ''}</td>
        <td>${fuente}</td>
        <td>${esc(d.periodo || '—')}</td>
        <td>${d.ultima_carga ? fecha(d.ultima_carga) : 'manual'}<div class="fr-nota">${esc(d.frecuencia || '')}</div></td>
        <td><span class="fr-badge" style="color:${e.color};background:${e.bg}">${esc(d.texto_estado && d.estado !== 'al_dia' && d.estado !== 'atrasado_tecnico' ? d.texto_estado : e.txt)}</span></td>
      </tr>`;
    }).join('');
    el.innerHTML = `
      <style>
        #${el.id} details { background:#fff; border:1px solid #dde2ec; border-radius:10px; padding:.6rem 1rem; margin:1rem 0; font-family:inherit; color:#1e293b; }
        #${el.id} summary { cursor:pointer; font-weight:700; font-size:.88rem; }
        #${el.id} .fr-wrap { overflow-x:auto; }
        #${el.id} table { width:100%; border-collapse:collapse; font-size:.78rem; margin-top:.6rem; }
        #${el.id} th { text-align:left; background:#f1f5f9; padding:.35rem .5rem; }
        #${el.id} td { padding:.35rem .5rem; border-top:1px solid #eef2f7; vertical-align:top; }
        #${el.id} .fr-nota { color:#64748b; font-size:.7rem; }
        #${el.id} .fr-badge { display:inline-block; padding:.1rem .45rem; border-radius:4px; font-weight:700; font-size:.7rem; white-space:nowrap; }
      </style>
      <details${alertas ? ' open' : ''}>
        <summary>📅 De dónde salen estos datos y cuándo se actualizaron
          ${alertas ? `<span class="fr-badge" style="color:#92400e;background:#fef3c7;margin-left:.4rem">${alertas} con atraso</span>` : '<span class="fr-badge" style="color:#15803d;background:#dcfce7;margin-left:.4rem">todo al día</span>'}
        </summary>
        <div class="fr-wrap"><table>
          <thead><tr><th>Dato</th><th>Fuente</th><th>Período que cubre</th><th>Última carga</th><th>Estado</th></tr></thead>
          <tbody>${filas}</tbody>
        </table></div>
        <div class="fr-nota" style="margin-top:.4rem">Que el sitio se haya actualizado hoy no significa que el dato sea de hoy: la columna “Período que cubre” dice a qué fecha corresponde.</div>
      </details>`;
  }
  const iniciar = () => document.querySelectorAll('[id^="frescura-ficha"]').forEach(montar);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})();
