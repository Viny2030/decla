/**
 * inocencia_overlay.js
 * ────────────────────
 * Agrega dos badges al modal de ficha individual, usando el endpoint
 * /api/constancias/{cuit}:
 *
 *   📊 Topes Régimen Simplificado — basado en ingresos/patrimonio (dato real)
 *   🛡️ Elegible Régimen Simplificado — topes + GCN (GCN pendiente de integrar)
 *
 * Ninguno de los dos implica adhesión efectiva al régimen: eso requiere
 * verificar la caracterización 618 en ARCA (ws_sr_constancia_inscripcion),
 * que todavía no está integrado.
 *
 * No modifica abrirFicha() directamente: la envuelve (monkey-patch),
 * deja correr la lógica original tal cual, y al final inyecta los badges.
 *
 * Si el endpoint no existe o falla, no se muestra nada — el resto del
 * card sigue funcionando exactamente igual que antes.
 *
 * Para activarlo, agregar en index.html (antes de </body>, después del
 * script principal):
 *   <script src="inocencia_overlay.js"></script>
 */
(function () {
  if (typeof window.abrirFicha !== 'function') {
    console.warn('[inocencia_overlay] abrirFicha no está definida — overlay no aplicado.');
    return;
  }
  const _abrirFichaOriginal = window.abrirFicha;

  function pillTopes(valor) {
    switch (valor) {
      case 'SI':
        return `<span class="pill pill-green" title="Ingresos y patrimonio dentro de los topes del Régimen Simplificado de Ganancias (RG 5820/2026)">📊 Topes Régimen Simplificado: Sí</span>`;
      case 'NO':
        return `<span class="pill pill-gray" title="Ingresos o patrimonio superan los topes del Régimen Simplificado de Ganancias">📊 Topes Régimen Simplificado: No</span>`;
      default:
        return `<span class="pill pill-yellow" title="Sin datos suficientes de ingresos/patrimonio para evaluar los topes">📊 Topes Régimen Simplificado: Sin datos</span>`;
    }
  }

  function pillElegibilidad(valor) {
    switch (valor) {
      case 'SI':
        return `<span class="pill pill-green" title="Cumple los requisitos de elegibilidad al Régimen Simplificado de Ganancias (Ley 27.799). No implica adhesión efectiva.">🛡️ Elegible Régimen Simplificado: Sí</span>`;
      case 'NO':
        return `<span class="pill pill-gray" title="No cumple los requisitos de elegibilidad al Régimen Simplificado de Ganancias">🛡️ Elegible Régimen Simplificado: No</span>`;
      default:
        return `<span class="pill pill-yellow" title="Pendiente: requiere padrón de Grandes Contribuyentes Nacionales (GCN) para completar la evaluación">🛡️ Elegible Régimen Simplificado: Sin datos</span>`;
    }
  }

  function normCuit(s) {
    return String(s || '').replace(/-/g, '').replace(/\.0$/, '').trim();
  }

  async function inyectarBadges(cuit) {
    const meta = document.querySelector('#modal-body .modal-meta');
    if (!meta) return;

    // Evitar duplicados si se vuelve a abrir el mismo modal
    meta.querySelectorAll('.regimen-badge').forEach(el => el.remove());

    const holderTopes = document.createElement('span');
    holderTopes.className = 'regimen-badge';
    holderTopes.innerHTML = `<span class="pill pill-gray">📊 Topes Régimen Simplificado: …</span>`;
    meta.appendChild(holderTopes);

    const holderEleg = document.createElement('span');
    holderEleg.className = 'regimen-badge';
    holderEleg.innerHTML = `<span class="pill pill-gray">🛡️ Elegible Régimen Simplificado: …</span>`;
    meta.appendChild(holderEleg);

    try {
      const resp = await fetch(`/api/constancias/${cuit}`);
      if (!resp.ok) {
        holderTopes.remove();
        holderEleg.remove();
        return;
      }
      const data = await resp.json();
      holderTopes.innerHTML = pillTopes(data.cumple_topes_regimen_simplificado);
      holderEleg.innerHTML  = pillElegibilidad(data.elegible_regimen_simplificado);
    } catch (e) {
      holderTopes.remove();
      holderEleg.remove();
    }
  }

  window.abrirFicha = function (poder, key) {
    const ret = _abrirFichaOriginal(poder, key);
    // Buscar el mismo registro que usó abrirFicha original para sacar el CUIT
    try {
      const norm = s => String(s || '').replace(/-/g, '').trim();
      const datos = (typeof DATA !== 'undefined' && DATA[poder]) || [];
      const r = datos.find(
        x => norm(x.cuit || x.cuil) === norm(key)
      ) || datos[parseInt(key)];
      if (r) {
        const cuit = normCuit(r.cuit || r.cuil || key);
        if (cuit) inyectarBadges(cuit);
      }
    } catch (e) {
      console.warn('[inocencia_overlay] no se pudo determinar el CUIT:', e);
    }
    return ret;
  };
})();
