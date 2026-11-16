'use strict';
// Unterrichtsbesuche: Lader fuer die vier Seiten (Uebersicht, Besuch, Erfassen, Einstellungen).
// Im alten Lehrerkalender kamen die Seitendaten (window.UB) aus Jinja-Vorlagen; hier holt dieser Lader sie per
// /api/ub/seite/..., fuellt die Teile, die dort serverseitig gerendert wurden, und startet danach die unveraendert
// uebernommenen Skripte (data-skripte am body) der Reihe nach.
(function () {
  const seite = document.body.dataset.seite;
  const nummer = (location.pathname.match(/\/unterrichtsbesuche\/(\d+)/) || [])[1];
  const url = seite === 'uebersicht' ? '/api/ub/seite/uebersicht' : seite === 'einstellungen' ? '/api/ub/seite/einstellungen' : '/api/ub/seite/besuch/' + nummer;

  const text = t => document.createTextNode(t == null ? '' : String(t));
  function knoten(tag, attr, ...kinder) {
    const n = document.createElement(tag);
    Object.entries(attr || {}).forEach(([k, v]) => { if (v != null) n.setAttribute(k, v); });
    kinder.flat().forEach(c => { if (c != null) n.appendChild(typeof c === 'string' ? text(c) : c); });
    return n;
  }
  const tagMonat = iso => iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' : '';
  const STATUS = { geplant: 'Geplant', laufend: 'Läuft', abgeschlossen: 'Abgeschlossen' };

  function laden(src) {
    return new Promise((ok, fehler) => {
      const s = document.createElement('script');
      s.src = '/static/' + src;
      s.onload = ok;
      s.onerror = () => fehler(new Error('Skript fehlt: ' + src));
      document.body.appendChild(s);
    });
  }

  // Uebersicht: „Anstehend & laufend“ und „Vergangene Besuche“ (im alten Tool Teil der Vorlage)
  function uebersicht(U) {
    const anstehend = document.getElementById('ubAnstehend');
    if (U.anstehend.length) {
      anstehend.appendChild(knoten('div', { class: 'ub-grid' }, U.anstehend.map(b => knoten('div', { class: 'ub-card' + (b.status === 'laufend' ? ' laufend' : '') },
        knoten('div', { class: 'ub-card-kopf' },
          knoten('span', { class: 'ub-card-datum' }, tagMonat(b.datum)),
          knoten('span', { class: 'ub-card-zeit' }, (b.beginn || '') + (b.ende ? '–' + b.ende : '')),
          knoten('span', { class: 'ub-status ' + b.status }, b.status === 'laufend' ? 'Läuft' : 'Geplant')),
        knoten('a', { class: 'ub-card-name', href: '/unterrichtsbesuche/' + b.id }, b.anwaerter),
        knoten('span', { class: 'ub-card-thema' }, b.thema || 'ohne Thema'),
        knoten('span', { class: 'ub-card-meta' }, (b.klasse || '—') + (b.raum ? ' · ' + b.raum : '') + (b.eintraege ? ' · ' + b.eintraege + ' Einträge' : '')),
        knoten('div', { class: 'ub-card-fuss' },
          knoten('a', { class: 'btn-sec', href: '/unterrichtsbesuche/' + b.id }, 'Details'),
          knoten('a', { class: 'btn', href: '/unterrichtsbesuche/' + b.id + '/erfassen' }, 'Erfassen'))))));
    } else {
      anstehend.appendChild(knoten('div', { class: 'card' }, knoten('p', { class: 'muted' }, 'Kein Besuch geplant. „+ Besuch“ legt einen an.')));
    }
    if (U.vergangen.length) {
      const ort = document.getElementById('ubVergangen');
      ort.appendChild(knoten('h2', { class: 'ub-h2' }, 'Vergangene Besuche'));
      const tabelle = knoten('table', { class: 'ub-liste' });
      U.vergangen.forEach(b => {
        const tr = knoten('tr', {},
          knoten('td', { style: 'white-space:nowrap;font-variant-numeric:tabular-nums' }, b.datum ? b.datum.slice(8, 10) + '.' + b.datum.slice(5, 7) + '.' + b.datum.slice(0, 4) : ''),
          knoten('td', {}, knoten('strong', {}, b.anwaerter)), knoten('td', {}, b.thema), knoten('td', { class: 'muted' }, b.klasse),
          knoten('td', { style: 'text-align:right' }, knoten('span', { class: 'ub-status ' + b.status }, STATUS[b.status] || b.status)));
        tr.addEventListener('click', () => { location.href = '/unterrichtsbesuche/' + b.id; });
        tabelle.appendChild(tr);
      });
      ort.appendChild(knoten('div', { class: 'card', style: 'padding:8px 14px' }, tabelle));
    }
  }

  // Besuch und Erfassen: Name, Thema, Status im Kopf (im alten Tool Teil der Vorlage)
  function besuch(U) {
    const b = U.besuch;
    document.title = b.anwaerter + ' · ' + tagMonat(b.datum) + ' · Unterrichtsbesuch';
    document.querySelectorAll('[data-ub="name"]').forEach(n => { n.textContent = b.anwaerter; });
    document.querySelectorAll('[data-ub="unterzeile"]').forEach(n => { n.textContent = (b.thema || 'ohne Thema') + (b.klasse ? ' · ' + b.klasse : ''); });
    document.querySelectorAll('[data-ub="id"]').forEach(n => { n.setAttribute('href', n.getAttribute('href').replace('{id}', b.id)); });
    const st = document.getElementById('ubdStatus');
    if (st) { st.textContent = STATUS[b.status] || b.status; st.className = 'ub-status ' + b.status; }
  }

  (async () => {
    let r;
    try { r = await fetch(url, { credentials: 'same-origin' }); } catch (e) { r = null; }
    if (r && r.status === 401) { location.href = '/anmelden'; return; }
    if (!r || !r.ok) {
      let t = 'Die Seite konnte nicht geladen werden.';
      try { t = (await r.json()).fehler || t; } catch (e) { /* kein JSON */ }
      document.body.insertBefore(knoten('div', { class: 'card', style: 'margin:16px' }, knoten('p', {}, t), knoten('a', { href: '/unterrichtsbesuche' }, 'Zur Übersicht')),
        document.body.firstChild);
      return;
    }
    window.UB = await r.json();
    if (seite === 'uebersicht') uebersicht(window.UB);
    if (seite === 'besuch' || seite === 'erfassen') besuch(window.UB);
    for (const s of (document.body.dataset.skripte || '').split(' ').filter(Boolean)) await laden(s);
  })();
})();
