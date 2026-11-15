'use strict';
// Unterrichtsplanung (Stufe C1, Voransichten A und C): Themenfolge je Strang (Klasse + Gruppe bzw. ganze Klasse) im
// Schuljahr, die Themen fliessen auf die Bloecke; Raster in den Ansichten Doppelstunden und Schuljahr; Bibliothek der
// Lernsituationen und Themen je Lernfeld mit "In Klasse uebernehmen".
const Planung = (() => {
  const el = L.el;
  const LF_FARBEN = ['#00639C', '#7b4fa8', '#8a9c00', '#d99000', '#0f8a8a', '#D4005E', '#5d6b7a', '#c2571a'];
  let ort = null;
  let P = null;                                  // Antwort von /api/planung
  const wahl = { schuljahr: null, klasse: null, gruppe: null, ansicht: 'bloecke', bildungsgang: null };
  let ziehen = null;                             // Thema, das gerade in der Liste gezogen wird

  const strangKey = s => s.klasse_id + ':' + (s.gruppe_id || 0);
  const tagKurz = iso => L.tag(iso).trim();
  const umfang = n => n + ' Bl';

  async function zeigen(ortEl, teil) {
    ort = ortEl;
    if (teil === 'bibliothek') return bibliothekZeigen();
    return planungZeigen();
  }

  // --- Planung eines Strangs ---

  async function laden() {
    const q = [];
    if (wahl.schuljahr) q.push('schuljahr=' + wahl.schuljahr);
    if (wahl.klasse) q.push('klasse=' + wahl.klasse + (wahl.gruppe ? '&gruppe=' + wahl.gruppe : ''));
    P = await L.api('GET', '/api/planung' + (q.length ? '?' + q.join('&') : ''));
    wahl.schuljahr = P.schuljahr_id;
    if (!wahl.klasse && P.straenge.length) {
      const erster = P.straenge.find(s => s.themen) || P.straenge[0];
      wahl.klasse = erster.klasse_id;
      wahl.gruppe = erster.gruppe_id;
      return laden();
    }
    if (wahl.klasse && !P.straenge.some(s => s.klasse_id === wahl.klasse && (s.gruppe_id || null) === (wahl.gruppe || null))) {
      wahl.klasse = null; wahl.gruppe = null;
      if (P.straenge.length) return laden();
    }
  }

  async function planungZeigen() {
    await laden();
    zeichnen();
  }

  async function neuLaden() {
    try { await laden(); zeichnen(); } catch (e) { L.meldung(e.message, true); }
  }

  function lfFarbe(lfid) {
    if (!P.plan || !lfid) return 'var(--leise)';
    const i = P.plan.lernfelder.findIndex(l => l.id === lfid);
    return i < 0 ? 'var(--leise)' : LF_FARBEN[i % LF_FARBEN.length];
  }

  function zeichnen() {
    const teile = [];
    if (!P.schuljahre.length) {
      teile.push(el('div', { class: 'banner warnung', text: 'Es gibt noch kein Schuljahr. Der Admin legt es unter Grunddaten → Schuljahr und Ferien an (erster und letzter Unterrichtstag).' }));
      return L.setzen(ort, teile);
    }
    const sj = el('select', { 'aria-label': 'Schuljahr', style: 'width:auto', onchange: () => { wahl.schuljahr = Number(sj.value); wahl.klasse = null; neuLaden(); } },
      P.schuljahre.map(j => el('option', { value: j.id, text: 'Schuljahr ' + j.name, selected: j.id === P.schuljahr_id ? true : null })));
    teile.push(el('div', { class: 'zeile' }, sj,
      P.straenge.length ? el('div', { class: 'zeile strang-wahl', role: 'group', 'aria-label': 'Klasse' }, P.straenge.map(s =>
        el('button', { type: 'button', class: 'chip-knopf' + (s.klasse_id === wahl.klasse && (s.gruppe_id || null) === (wahl.gruppe || null) ? ' an' : ''),
          onclick: () => { wahl.klasse = s.klasse_id; wahl.gruppe = s.gruppe_id; neuLaden(); } },
        s.name, s.themen ? el('span', { class: 'chip klein', text: String(s.themen) }) : null))) : null));
    if (!P.straenge.length) {
      teile.push(el('div', { class: 'banner' }, 'In diesem Schuljahr steht noch keine Klasse in deinem Stundenplan. ',
        el('a', { href: '#einstellungen', text: 'Stundenplan einrichten' })));
      return L.setzen(ort, teile);
    }
    const p = P.plan;
    const s = P.straenge.find(x => x.klasse_id === wahl.klasse && (x.gruppe_id || null) === (wahl.gruppe || null));
    teile.push(el('div', { class: 'zeile' },
      el('h2', { text: s ? s.name : '' }),
      el('span', { class: 'leise klein', text: p.summe.bloecke + ' Blöcke im Schuljahr · ' + p.summe.verplant + ' verplant · ' + p.summe.frei + ' frei' }),
      p.summe.ueberlauf ? el('span', { class: 'chip rot', text: p.summe.ueberlauf + ' Bl passen nicht mehr' }) : null,
      p.spuren.length ? el('span', { class: 'chip', title: 'Diese Lernfelder haben eigene Blöcke im Stundenplan', text: 'eigene Blöcke: ' + p.spuren.map(x => x.nummer).join(', ') }) : null,
      el('span', { class: 'rechts' },
        el('div', { class: 'segment', role: 'group', 'aria-label': 'Ansicht' },
          [['bloecke', 'Doppelstunden'], ['schuljahr', 'Schuljahr']].map(([a, t]) =>
            el('button', { type: 'button', class: wahl.ansicht === a ? 'an' : null, onclick: () => { wahl.ansicht = a; zeichnen(); } }, t))),
        el('button', { type: 'button', onclick: () => themaBearbeiten(null) }, L.symbol('plus'), 'Thema'),
        el('a', { class: 'knopf', href: '#planung-bibliothek' }, L.symbol('pakete'), 'Aus Bibliothek'))));
    if (!p.themen.length) {
      teile.push(el('div', { class: 'leer' }, 'Noch keine Themen. Übernimm Lernsituationen aus der ',
        el('a', { href: '#planung-bibliothek', text: 'Bibliothek' }), ' oder lege mit „+ Thema“ eines an.'));
    }
    if (p.themen.length) {
      const tabelle = wahl.ansicht === 'schuljahr' ? rasterSchuljahr(p) : rasterBloecke(p);
      const scroll = el('div', { class: 'r-scroll' }, tabelle);
      teile.push(scroll);
      teile.push(legende(p));
      L.setzen(ort, teile);
      const heute = scroll.querySelector('th.ab-heute') || scroll.querySelector('th.heute');   // zur aktuellen Woche springen
      if (heute) scroll.scrollLeft = Math.max(0, heute.offsetLeft - 260 - 3 * heute.offsetWidth);
      return;
    }
    L.setzen(ort, teile);
  }

  function titelZelle(t, i) {
    const zelle = el('td', { class: 'auf', title: t.titel + (t.ls_titel ? ' · ' + t.ls_titel : '') },
      t.lernfeld ? el('span', { class: 'kz', style: 'color:' + lfFarbe(t.lernfeld_id), text: t.lernfeld }) : null,
      el('button', { type: 'button', class: 'leicht thema-name', onclick: () => themaBearbeiten(t) }, t.titel),
      el('span', { class: 'art', text: umfang(t.bloecke) }),
      t.ueberlauf ? el('span', { class: 'chip rot klein', text: '−' + t.ueberlauf }) : null,
      t.nadel === 'fehlt' ? el('span', { class: 'chip gelb klein', title: 'Der festgesetzte Block findet nicht statt', text: 'Nadel?' }) : null);
    const tr = zelle;
    tr.draggable = true;
    tr.addEventListener('dragstart', ev => { ziehen = t.id; ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', String(t.id)); });
    tr.addEventListener('dragover', ev => { if (ziehen && ziehen !== t.id) { ev.preventDefault(); tr.classList.add('ziel'); } });
    tr.addEventListener('dragleave', () => tr.classList.remove('ziel'));
    tr.addEventListener('drop', async ev => {
      ev.preventDefault(); tr.classList.remove('ziel');
      const id = ziehen; ziehen = null;
      if (!id || id === t.id) return;
      try { await L.api('POST', '/api/thema/' + id + '/stelle', { stelle: i }); await neuLaden(); } catch (e) { L.meldung(e.message, true); }
    });
    return zelle;
  }

  // Zeilen mit Zwischenzeilen fuer Lernsituationen
  function zeilen(p, zellen) {
    const rows = [];
    let ls = null;
    p.themen.forEach((t, i) => {
      if (t.ls_titel && t.ls_titel !== ls) rows.push(el('tr', { class: 'paket' }, el('td', { colspan: 999 }, el('span', { class: 'kleben' }, 'Lernsituation', el('span', { class: 'pm', text: t.ls_titel })))));
      ls = t.ls_titel || null;
      rows.push(el('tr', { style: '--b:' + lfFarbe(t.lernfeld_id) }, titelZelle(t, i), zellen(t)));
    });
    return rows;
  }

  function rasterBloecke(p) {
    const spalten = p.bloecke.map((b, i) => ({ ...b, i, nutzbar: true }))
      .concat(p.weg.map(b => ({ ...b, nutzbar: false })))
      .sort((a, b) => (a.datum + a.beginn).localeCompare(b.datum + b.beginn));
    const ersterAbHeute = spalten.find(c => c.datum >= p.heute);
    const kopf = el('tr', {}, el('th', { class: 'links', text: 'Thema' }), spalten.map(c => el('th', {
      class: (c.datum === p.heute ? 'heute' : '') + (c === ersterAbHeute ? ' ab-heute' : '') + (c.nutzbar ? '' : ' aus'),
      title: L.tag(c.datum, true) + ' ' + c.beginn + (c.nutzbar ? (c.art !== 'regulaer' ? ' · ' + (c.art === 'zusatz' ? 'Zusatzstunde' : 'verschoben') : '') : ' · ' + (c.zustand === 'ausfall' ? 'fällt aus' : c.zustand === 'vertreten' ? 'vertreten' : 'verschoben') + (c.grund ? ': ' + c.grund : '')) },
    L.TAGE[new Date(c.datum + 'T12:00:00').getDay()], el('br'), c.datum.slice(8, 10) + '.' + c.datum.slice(5, 7) + '.')));
    const zellen = t => spalten.map(c => {
      const td = el('td', { class: 't' + (c.datum === p.heute ? ' heute' : '') + (c.nutzbar ? ' kann' : ' aus') });
      if (!c.nutzbar) return td;
      if (c.thema_id === t.id) {
        td.appendChild(el('span', { class: 'bal' + (c.teil === 1 ? ' a' : '') + (c.teil === c.von || c.teil === t.zugeteilt ? ' e' : '') }));
        if (c.teil === 1 && t.nadel === 'ok') td.appendChild(el('span', { class: 'nadel', title: 'festgesetzt' }, L.symbol('pin')));
      }
      td.addEventListener('click', ev => blockMenue(ev, t, c));
      return td;
    });
    return el('table', { class: 'lp' }, el('thead', {}, kopf), el('tbody', {}, zeilen(p, zellen)));
  }

  function rasterSchuljahr(p) {
    const jeWoche = {};
    p.bloecke.forEach(b => {
      const m = montagVon(b.datum);
      if (b.thema_id) (jeWoche[m + ':' + b.thema_id] = (jeWoche[m + ':' + b.thema_id] || 0) + 1);
    });
    const kopf = el('tr', {}, el('th', { class: 'links', text: 'Thema' }), p.wochen.map(w => el('th', {
      class: (w.heute ? 'heute' : '') + (w.frei ? ' ferien' : ''), title: (w.ferien ? w.ferien + ' · ' : '') + 'ab ' + L.tag(w.montag, true) },
    'KW', el('br'), String(w.kw))));
    const zellen = t => p.wochen.map(w => {
      const n = jeWoche[w.montag + ':' + t.id] || 0;
      const td = el('td', { class: 't kw' + (w.heute ? ' heute' : '') + (w.frei ? ' ferien' : '') + (n ? ' kann' : '') });
      if (n) {
        const davor = jeWoche[plusTage(w.montag, -7) + ':' + t.id];
        const danach = jeWoche[plusTage(w.montag, 7) + ':' + t.id];
        td.appendChild(el('span', { class: 'bal' + (davor ? '' : ' a') + (danach ? '' : ' e') }));
        td.appendChild(el('span', { class: 'anzahl', text: String(n) }));
        td.title = t.titel + ': ' + n + (n === 1 ? ' Block' : ' Blöcke') + ' in KW ' + w.kw;
        td.addEventListener('click', () => { wahl.ansicht = 'bloecke'; zeichnen(); });
      }
      return td;
    });
    return el('table', { class: 'lp' }, el('thead', {}, kopf), el('tbody', {}, zeilen(p, zellen)));
  }

  function legende(p) {
    const lfs = [...new Set(p.themen.map(t => t.lernfeld_id).filter(Boolean))];
    return el('div', { class: 'legende' },
      lfs.map(id => el('span', {}, el('i', { class: 'farbe', style: 'background:' + lfFarbe(id) }), (p.lernfelder.find(l => l.id === id) || {}).nummer || '')),
      el('span', {}, el('i', { class: 'm-aus' }), 'Ausfall, vertreten, verschoben'),
      el('span', {}, L.symbol('pin'), 'festgesetzt (Tipp auf einen Block)'),
      el('span', { class: 'leise', text: 'Reihenfolge: Thema am Namen ziehen' }));
  }

  function montagVon(iso) {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return isoVon(d);
  }
  function plusTage(iso, n) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return isoVon(d); }
  function isoVon(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  // Tipp auf einen Block in der Zeile eines Themas: festsetzen bzw. Stecknadel loesen
  function blockMenue(ev, t, c) {
    const alt = document.getElementById('wp-menue');
    if (alt) alt.remove();
    const punkte = [['pin', 'Hier festsetzen: beginnt ' + tagKurz(c.datum) + ' ' + c.beginn, () => festsetzen(t, c.datum, c.beginn)]];
    if (t.nadel) punkte.push(['undo', 'Stecknadel lösen (fließt wieder)', () => festsetzen(t, null, null)]);
    punkte.push(['stift', 'Thema bearbeiten …', () => themaBearbeiten(t)]);
    const m = el('div', { class: 'wp-menue', id: 'wp-menue', role: 'menu' }, el('div', { class: 'mk', text: t.titel }),
      punkte.map(([sym, text, aktion]) => el('button', { type: 'button', role: 'menuitem', onclick: () => { m.remove(); aktion(); } }, L.symbol(sym), text)));
    document.body.appendChild(m);
    m.style.left = Math.max(8, Math.min(ev.pageX, document.documentElement.clientWidth + scrollX - m.offsetWidth - 8)) + 'px';
    m.style.top = Math.max(8, Math.min(ev.pageY + 4, scrollY + innerHeight - m.offsetHeight - 8)) + 'px';
    ev.stopPropagation();
    m.querySelector('button').focus();
  }
  document.addEventListener('click', ev => { const m = document.getElementById('wp-menue'); if (m && !ev.target.closest('#wp-menue') && !ev.target.closest('.lp td.t')) m.remove(); });

  async function festsetzen(t, datum, beginn) {
    try { await L.api('POST', '/api/thema/' + t.id + '/festsetzen', { datum, beginn }); await neuLaden(); } catch (e) { L.meldung(e.message, true); }
  }

  async function themaBearbeiten(t) {
    const p = P.plan;
    const titel = el('input', { maxlength: 200, value: t ? t.titel : '', placeholder: 'z. B. Ablaufsteuerung mit GRAFCET' });
    const bloecke = el('input', { type: 'number', min: 1, max: 400, value: t ? t.bloecke : 2, style: 'width:110px' });
    const lf = el('select', {}, el('option', { value: '', text: '– ohne –' }), p.lernfelder.map(l =>
      el('option', { value: l.id, text: l.nummer + ' ' + l.name, selected: t && t.lernfeld_id === l.id ? true : null })));
    const ls = el('input', { maxlength: 200, value: t ? t.ls_titel : '', placeholder: 'freiwillig' });
    const hinweis = el('textarea', { maxlength: 4000, rows: 3, placeholder: 'Lehrstoff, Material, Hinweise (für „Lehrstoff kopieren“ in Stufe C2)' });
    hinweis.value = t ? t.hinweis : '';
    const weitere = t ? [
      { text: 'Entfernen', klasse: 'warnen', speichern: () => L.api('POST', '/api/thema/' + t.id + '/loeschen', {}) },
    ] : [];
    const r = await L.dialog({
      titel: t ? 'Thema' : 'Neues Thema', weitere,
      inhalt: el('div', { class: 'felder' },
        L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Umfang in Blöcken', bloecke, '1 Block = 1 Doppelstunde'), L.feld('Lernfeld', lf)),
        L.feld('Lernsituation', ls), L.feld('Hinweis', hinweis),
        t ? el('div', { class: 'zeile' },
          L.nebenknopf('↑ nach oben', () => schieben(t, -1), 'klein'),
          L.nebenknopf('↓ nach unten', () => schieben(t, 1), 'klein'),
          t.von ? el('span', { class: 'leise klein', text: 'läuft ' + tagKurz(t.von) + (t.bis !== t.von ? ' bis ' + tagKurz(t.bis) : '') }) : null) : null),
      speichern: () => L.api('POST', t ? '/api/thema/' + t.id : '/api/thema', {
        klasse_id: wahl.klasse, gruppe_id: wahl.gruppe, schuljahr_id: wahl.schuljahr,
        titel: titel.value, bloecke: Number(bloecke.value), lernfeld_id: lf.value || null, ls_titel: ls.value, hinweis: hinweis.value }),
    });
    if (r) await neuLaden();
  }

  async function schieben(t, richtung) {
    try { await L.api('POST', '/api/thema/' + t.id + '/schieben', { richtung }); await neuLaden(); L.meldung('Verschoben.'); } catch (e) { L.meldung(e.message, true); }
  }

  // --- Bibliothek ---

  let B = null;
  let konto = null;

  async function bibliothekZeigen() {
    const [b, ich] = await Promise.all([
      L.api('GET', '/api/bibliothek' + (wahl.bildungsgang ? '?bildungsgang=' + wahl.bildungsgang : '')),
      konto ? Promise.resolve({ konto }) : L.api('GET', '/api/ich')]);
    B = b;
    konto = ich.konto;
    wahl.bildungsgang = B.bildungsgang_id;
    bibliothekZeichnen();
  }

  const darf = x => konto.rolle === 'admin' || x.besitzer_id === konto.id;

  function bibliothekZeichnen() {
    const teile = [];
    if (!B.bildungsgaenge.length) {
      return L.setzen(ort, el('div', { class: 'banner warnung', text: 'Es gibt noch keinen Bildungsgang. Der Admin legt ihn unter Grunddaten an.' }));
    }
    const bg = B.bildungsgaenge.find(x => x.id === B.bildungsgang_id);
    if (B.bildungsgaenge.length > 1) {
      teile.push(el('div', { class: 'segment', role: 'group', 'aria-label': 'Bildungsgang' }, B.bildungsgaenge.map(x =>
        el('button', { type: 'button', class: x.id === B.bildungsgang_id ? 'an' : null, onclick: async () => { wahl.bildungsgang = x.id; await bibliothekZeigen(); } }, x.name))));
    }
    teile.push(el('p', { class: 'leise', style: 'max-width:80ch', text: 'Lernsituationen und Themen je ' + (bg.einheit === 'modul' ? 'Modul' : 'Lernfeld') +
      ', für alle im Bildungsgang sichtbar. Ändern darf, wer etwas angelegt hat. „In Klasse übernehmen“ kopiert in deine Planung; dort kannst du alles anpassen, ohne die Bibliothek zu verändern.' }));
    if (!B.lernfelder.length) teile.push(el('div', { class: 'leer', text: 'In diesem Bildungsgang gibt es noch keine Lernfelder. Der Admin legt sie unter Grunddaten an.' }));
    const stufen = [{ id: null, name: 'ohne Stufe' }].concat(bg.stufen);
    for (const st of stufen) {
      const lfs = B.lernfelder.filter(l => (l.stufe_id || null) === st.id);
      if (!lfs.length) continue;
      teile.push(el('h2', { class: 'stufe-titel', text: st.name }));
      lfs.forEach(lf => teile.push(lernfeldKarte(lf)));
    }
    L.setzen(ort, teile);
  }

  function lernfeldKarte(lf) {
    const summe = lf.lernsituationen.reduce((n, x) => n + x.umfang, 0) + lf.themen.reduce((n, x) => n + x.bloecke, 0);
    const offen = lf.lernsituationen.length + lf.themen.length > 0;
    return el('details', { class: 'karte lf-karte', open: offen ? true : null },
      el('summary', { class: 'zeile' }, el('b', { class: 'mono', text: lf.nummer }), el('b', { text: lf.name }),
        el('span', { class: 'leise klein', text: lf.stunden ? lf.stunden + ' Std = ' + Math.round(lf.stunden / 2) + ' Bl' : 'ohne Stundenansatz' }),
        summe ? el('span', { class: 'chip', title: 'Summe der Bausteine', text: summe + ' Bl in der Bibliothek' }) : null),
      el('div', { class: 'stapel', style: 'gap:10px;margin-top:10px' },
        lf.lernsituationen.map(ls => lsKarte(lf, ls)),
        lf.themen.length ? el('div', { class: 'ka' }, el('div', { class: 'etikett', text: 'Einzelne Themen ohne Lernsituation' }),
          lf.themen.map(t => themaZeile(lf, t))) : null,
        el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'klein', onclick: () => bausteinBearbeiten(lf, null, 'ls') }, L.symbol('plus'), 'Neue Lernsituation'),
          el('button', { type: 'button', class: 'klein', onclick: () => bausteinBearbeiten(lf, null, 'thema') }, L.symbol('plus'), 'Neues Thema'))));
  }

  function lsKarte(lf, ls) {
    return el('div', { class: 'ka' },
      el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: 'LS' }), el('b', { text: ls.titel }),
        el('span', { class: 'leise klein', text: umfang(ls.umfang) }),
        el('span', { class: 'rechts' },
          darf(ls) ? el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Lernsituation bearbeiten', onclick: () => bausteinBearbeiten(lf, ls, 'ls') }, L.symbol('stift')) : null,
          el('button', { type: 'button', class: 'klein', onclick: () => uebernehmen(lf, ls) }, L.symbol('plus'), 'In Klasse übernehmen'))),
      ls.themen.length ? el('table', { class: 'liste' }, el('tbody', {}, ls.themen.map(t => el('tr', {},
        el('td', { text: t.titel }), el('td', { class: 'leise klein', text: t.hinweis ? t.hinweis.split('\n')[0].slice(0, 60) : '' }),
        el('td', { class: 'mono', style: 'text-align:right;white-space:nowrap', text: umfang(t.bloecke) }),
        el('td', { class: 'knoepfe' }, darf(t) ? el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Thema bearbeiten',
          onclick: () => bausteinBearbeiten(lf, t, 'thema') }, L.symbol('stift')) : null)))))
        : el('p', { class: 'leise klein', text: 'Noch nicht in Themen aufgeteilt. Fließt in der Klasse als ein Stück mit ' + umfang(ls.umfang) + '.' }),
      el('div', { class: 'zeile leise klein' },
        darf(ls) ? el('button', { type: 'button', class: 'leicht klein', onclick: () => bausteinBearbeiten(lf, null, 'thema', ls) }, L.symbol('plus'), 'Thema in dieser LS') : null,
        el('span', { text: 'angelegt von ' + (ls.besitzer_id === konto.id ? 'dir' : ls.besitzer || '–') + (ls.genutzt.length ? ' · genutzt in ' + ls.genutzt.join(', ') : '') })));
  }

  function themaZeile(lf, t) {
    return el('div', { class: 'zeile' }, el('span', { text: t.titel }), el('span', { class: 'leise klein mono', text: umfang(t.bloecke) }),
      el('span', { class: 'rechts' },
        darf(t) ? el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Thema bearbeiten', onclick: () => bausteinBearbeiten(lf, t, 'thema') }, L.symbol('stift')) : null,
        el('button', { type: 'button', class: 'klein', onclick: () => uebernehmen(lf, t) }, L.symbol('plus'), 'In Klasse übernehmen')));
  }

  async function bausteinBearbeiten(lf, b, art, ls) {
    const titel = el('input', { maxlength: 200, value: b ? b.titel : '', placeholder: art === 'ls' ? 'z. B. Förderanlage automatisieren' : 'z. B. SPS-Grundlagen' });
    const bloecke = el('input', { type: 'number', min: art === 'ls' ? 0 : 1, max: 400, value: b ? b.bloecke : (art === 'ls' ? 0 : 2), style: 'width:110px' });
    const hinweis = el('textarea', { maxlength: 4000, rows: 3, placeholder: 'Lehrstoff, Material, Hinweise' });
    hinweis.value = b ? b.hinweis : '';
    const weitere = [];
    if (b) {
      weitere.push({ text: 'Löschen', klasse: 'warnen', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/loeschen', {}) });
      weitere.push({ text: '↑', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/schieben', { richtung: -1 }) });
      weitere.push({ text: '↓', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/schieben', { richtung: 1 }) });
    }
    const r = await L.dialog({
      titel: (b ? '' : 'Neue ') + (art === 'ls' ? 'Lernsituation' : 'Thema') + ' · ' + lf.nummer, weitere,
      inhalt: el('div', { class: 'felder' },
        ls ? el('p', { class: 'leise klein', text: 'in „' + ls.titel + '“' }) : null,
        L.feld('Titel', titel),
        L.feld(art === 'ls' ? 'Umfang ohne Themen (Blöcke)' : 'Umfang in Blöcken', bloecke,
          art === 'ls' ? 'Zählt nur, solange die LS keine Themen hat' : '1 Block = 1 Doppelstunde'),
        L.feld('Hinweis', hinweis)),
      speichern: () => L.api('POST', b ? '/api/baustein/' + b.id : '/api/baustein', { art, lernfeld_id: lf.id, ls_id: ls ? ls.id : null,
        titel: titel.value, bloecke: Number(bloecke.value), hinweis: hinweis.value }),
    });
    if (r) await bibliothekZeigen();
  }

  async function uebernehmen(lf, b) {
    let pl;
    try { pl = await L.api('GET', '/api/planung' + (wahl.schuljahr ? '?schuljahr=' + wahl.schuljahr : '')); } catch (e) { L.meldung(e.message, true); return; }
    const passend = pl.straenge.filter(s => s.bildungsgang_id === B.bildungsgang_id);
    if (!pl.schuljahre.length) { L.meldung('Es gibt noch kein Schuljahr (legt der Admin an).', true); return; }
    if (!passend.length) { L.meldung('Du hast in diesem Schuljahr keine Klasse dieses Bildungsgangs im Stundenplan.', true); return; }
    const vorher = passend.find(s => s.klasse_id === wahl.klasse && (s.gruppe_id || null) === (wahl.gruppe || null)) || passend[0];
    const strang = el('select', {}, passend.map(s => el('option', { value: strangKey(s), text: s.name, selected: s === vorher ? true : null })));
    const r = await L.dialog({
      titel: 'In Klasse übernehmen', knopf: 'Übernehmen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('p', { class: 'klein' }, el('b', { text: b.titel }), ' · ' + umfang(b.umfang || b.bloecke) + (b.themen && b.themen.length ? ' in ' + b.themen.length + ' Themen' : '')),
        L.feld('Klasse bzw. Gruppe · Schuljahr ' + (pl.schuljahre.find(j => j.id === pl.schuljahr_id) || {}).name, strang),
        el('p', { class: 'leise klein', text: 'Kommt ans Ende der Themenfolge. Die Reihenfolge änderst du in der Planung.' })),
      speichern: () => {
        const s = passend.find(x => strangKey(x) === strang.value);
        return L.api('POST', '/api/planung/uebernehmen', { klasse_id: s.klasse_id, gruppe_id: s.gruppe_id, schuljahr_id: pl.schuljahr_id, baustein_id: b.id })
          .then(x => ({ ...x, s }));
      },
    });
    if (!r) return;
    wahl.schuljahr = pl.schuljahr_id; wahl.klasse = r.s.klasse_id; wahl.gruppe = r.s.gruppe_id;
    L.meldung(r.id + (r.id === 1 ? ' Thema' : ' Themen') + ' in ' + r.s.name + ' übernommen.');
    await bibliothekZeigen();
  }

  return { zeigen };
})();
