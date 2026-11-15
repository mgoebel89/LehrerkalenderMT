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

  function titelZelle(t, i) {
    const zelle = el('td', { class: 'auf', title: t.titel + (t.ls_titel ? ' · ' + t.ls_titel : '') },
      t.lernfeld ? el('span', { class: 'kz', style: 'color:' + lfFarbe(t.lernfeld_id), text: t.lernfeld }) : null,
      el('button', { type: 'button', class: 'leicht thema-name', onclick: () => (t.pruefung_id ? (location.hash = '#pruefung-' + t.pruefung_id) : themaBearbeiten(t)) }, t.titel),
      t.pruefung_id ? el('span', { class: 'chip rot klein', text: 'Prüfung' }) : null,
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
      rows.push(el('tr', { style: '--b:' + (t.pruefung_id ? 'var(--rot)' : lfFarbe(t.lernfeld_id)) }, titelZelle(t, i), zellen(t)));
    });
    return rows;
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
      el('span', { class: 'leise klein', text: p.summe.bloecke + ' Blöcke im Schuljahr · noch ' + p.summe.rest + ' · ' + p.summe.bedarf + ' verplant · ' + p.summe.frei + ' frei' }),
      p.summe.ueberlauf ? el('span', { class: 'chip rot', text: p.summe.ueberlauf + ' Bl passen nicht mehr' }) : null,
      p.summe.ist_offen ? el('span', { class: 'chip gelb', title: 'Gehaltene Stunden ohne Ist-Bestätigung' }, L.symbol('offen'), p.summe.ist_offen + ' ohne Ist') : null,
      p.spuren.length ? el('span', { class: 'chip', title: 'Diese Lernfelder haben eigene Blöcke im Stundenplan', text: 'eigene Blöcke: ' + p.spuren.map(x => x.nummer).join(', ') }) : null,
      el('span', { class: 'rechts' },
        el('div', { class: 'segment', role: 'group', 'aria-label': 'Ansicht' },
          [['bloecke', 'Doppelstunden'], ['tage', 'Tage'], ['schuljahr', 'Schuljahr']].map(([a, t]) =>
            el('button', { type: 'button', class: wahl.ansicht === a ? 'an' : null, onclick: () => { wahl.ansicht = a; zeichnen(); } }, t))),
        el('button', { type: 'button', onclick: () => themaBearbeiten(null) }, L.symbol('plus'), 'Thema'),
        el('a', { class: 'knopf', href: '#planung-bibliothek' }, L.symbol('pakete'), 'Aus Bibliothek'))));
    if (!p.themen.length) {
      teile.push(el('div', { class: 'leer' }, 'Noch keine Themen. Übernimm Lernsituationen aus der ',
        el('a', { href: '#planung-bibliothek', text: 'Bibliothek' }), ' oder lege mit „+ Thema“ eines an.'));
      return L.setzen(ort, teile);
    }
    const tabelle = wahl.ansicht === 'schuljahr' ? rasterSchuljahr(p) : wahl.ansicht === 'tage' ? rasterTage(p) : rasterBloecke(p);
    const scroll = el('div', { class: 'r-scroll' }, tabelle);
    teile.push(scroll, legende(p), bilanz(p));
    L.setzen(ort, teile);
    const ziel = wahl.springe ? [...scroll.querySelectorAll('th[data-datum]')].find(th => th.dataset.datum >= wahl.springe) : null;
    wahl.springe = null;
    const heute = ziel || scroll.querySelector('th.ab-heute') || scroll.querySelector('th.heute');   // zur gewaehlten bzw. aktuellen Woche
    if (heute) scroll.scrollLeft = Math.max(0, heute.offsetLeft - 270 - 2 * heute.offsetWidth);
  }

  // Spalten nach Datum: Tage mit ihren Bloecken (auch ausgefallene) und dazwischen die Ferienabschnitte
  function tagesGruppen(p) {
    const bl = p.bloecke.map(b => ({ ...b, nutzbar: true })).concat(p.weg.map(b => ({ ...b, nutzbar: false })))
      .sort((a, b) => (a.datum + a.beginn).localeCompare(b.datum + b.beginn));
    const gruppen = [];
    bl.forEach(c => {
      const g = gruppen[gruppen.length - 1];
      if (g && g.datum === c.datum) g.spalten.push(c);
      else gruppen.push({ typ: 'tag', datum: c.datum, spalten: [c] });
    });
    const z = p.klasse_zeitraum || {};
    p.ferien.filter(f => (!z.ende || f.von <= z.ende) && (!z.beginn || f.bis >= z.beginn))   // ausserhalb des Unterrichts ohne Belang
      .forEach(f => gruppen.push({ typ: 'ferien', datum: f.von, f }));
    if (z.beginn) gruppen.push({ typ: 'ferien', datum: z.beginn, f: { name: 'Unterrichtsbeginn', von: z.beginn, bis: z.beginn, marke: true } });
    if (z.ende) gruppen.push({ typ: 'ferien', datum: plusTage(z.ende, 1), f: { name: 'Ausschulung', von: z.ende, bis: z.ende, marke: true } });
    gruppen.sort((a, b) => a.datum.localeCompare(b.datum) || (a.typ === 'ferien' ? -1 : 1));
    let kwVorher = null;
    gruppen.forEach(g => {
      if (g.typ !== 'tag') return;
      const kw = kwVon(g.datum);
      g.kw = kw;
      g.w2 = kw % 2 === 0;                         // Wochen abwechselnd leicht getoent
      g.neueWoche = kw !== kwVorher;
      kwVorher = kw;
    });
    const ab = gruppen.find(g => g.typ === 'tag' && g.datum >= p.heute);
    if (ab) ab.abHeute = true;
    return gruppen;
  }

  function kwVon(iso) {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
    const jan4 = new Date(d.getFullYear(), 0, 4, 12);
    return 1 + Math.round(((d - jan4) / 864e5 - 3 + ((jan4.getDay() + 6) % 7)) / 7);
  }

  const tagText = iso => L.TAGE[new Date(iso + 'T12:00:00').getDay()] + ' ' + iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.';

  function ferienKopf(f, rowspan) {
    if (f.marke) {
      return el('th', { class: 'ferien-sp marke', rowspan: rowspan || null,
        title: f.name === 'Ausschulung' ? 'Letzter Unterrichtstag der Klasse: ' + L.tag(f.von, true) : 'Erster Unterrichtstag der Klasse: ' + L.tag(f.von, true) },
      el('span', { class: 'senkrecht', text: f.name + ' ' + L.tag(f.von).trim().slice(3) }));
    }
    return el('th', { class: 'ferien-sp', rowspan: rowspan || null, title: f.name + ': ' + L.tag(f.von, true) + (f.bis !== f.von ? ' – ' + L.tag(f.bis, true) : '') },
      el('span', { class: 'senkrecht', text: f.name }));
  }

  function wochenKlasse(g) {
    return (g.w2 ? ' w2' : '') + (g.neueWoche ? ' wochenstart' : '');
  }

  // Ist-Markierung an einem belegten Block
  function istMarke(c) {
    if (!c.nutzbar || !c.thema_id) return null;
    if (c.ist === 'ok') return el('span', { class: 'istm ok', title: 'gehalten, wie geplant', text: '✓' });
    if (c.ist === 'mehr') return el('span', { class: 'istm mehr', title: 'braucht 1 Block mehr', text: '+1' });
    if (c.ist === 'fertig') return el('span', { class: 'istm fertig', title: 'Thema hier fertig', text: '⊣' });
    if (c.vergangen) return el('span', { class: 'istm offen', title: 'Ist fehlt' });
    return null;
  }

  function rasterBloecke(p) {
    const gruppen = tagesGruppen(p);
    const kopf1 = el('tr', {}, el('th', { class: 'links', rowspan: 2, text: 'Thema' }), gruppen.map(g => g.typ === 'ferien' ? ferienKopf(g.f, 2)
      : el('th', { class: 'tag-kopf tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (g.abHeute ? ' ab-heute' : ''), colspan: g.spalten.length,
        'data-datum': g.datum },
        tagText(g.datum), g.neueWoche ? el('span', { class: 'kw', text: ' KW ' + g.kw }) : null)));
    const kopf2 = el('tr', {}, gruppen.map(g => g.typ === 'ferien' ? null : g.spalten.map((c, n) => el('th', {
      class: 'zeit' + (n === 0 ? ' tag-start' : '') + wochenKlasse(g) + (c.nutzbar ? '' : ' aus'),
      title: L.tag(c.datum, true) + ' ' + c.beginn + (c.nutzbar ? (c.art !== 'regulaer' ? ' · ' + (c.art === 'zusatz' ? 'Zusatzstunde' : 'verschoben') : '')
        : ' · ' + (c.zustand === 'ausfall' ? 'fällt aus' : c.zustand === 'vertreten' ? 'vertreten' : 'verschoben') + (c.grund ? ': ' + c.grund : '')) },
    c.beginn))));
    const zellen = t => gruppen.map(g => g.typ === 'ferien' ? el('td', { class: 'ferien-sp' + (g.f.marke ? ' marke' : '') }) : g.spalten.map((c, n) => {
      const td = el('td', { class: 't' + (n === 0 ? ' tag-start' : '') + wochenKlasse(g) + (c.datum === p.heute ? ' heute' : '') + (c.nutzbar ? ' kann' : ' aus') });
      if (!c.nutzbar) return td;
      if (c.thema_id === t.id) {
        td.appendChild(el('span', { class: 'bal' + (c.teil === 1 ? ' a' : '') + (c.teil === c.von || c.teil === t.zugeteilt ? ' e' : '') }));
        if (c.teil === 1 && t.nadel === 'ok') td.appendChild(el('span', { class: 'nadel', title: 'festgesetzt' }, L.symbol('pin')));
        const m = istMarke(c);
        if (m) td.appendChild(m);
      }
      td.addEventListener('click', ev => blockMenue(ev, t, c));
      td.addEventListener('contextmenu', ev => blockMenue(ev, t, c));
      return td;
    }));
    return el('table', { class: 'lp lp-tage' }, el('thead', {}, kopf1, kopf2), el('tbody', {}, zeilen(p, zellen)));
  }

  // Tage: eine Spalte je Unterrichtstag, darin je Block ein Abschnitt (geteilte Zelle, wenn zwei Themen den Tag teilen)
  function rasterTage(p) {
    const gruppen = tagesGruppen(p);
    const kopf = el('tr', {}, el('th', { class: 'links', text: 'Thema' }), gruppen.map(g => g.typ === 'ferien' ? ferienKopf(g.f)
      : el('th', { class: 'tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (g.abHeute ? ' ab-heute' : ''),
        title: L.tag(g.datum, true) + ' · ' + g.spalten.length + (g.spalten.length === 1 ? ' Block' : ' Blöcke') },
      L.TAGE[new Date(g.datum + 'T12:00:00').getDay()], el('br'), g.datum.slice(8, 10) + '.' + g.datum.slice(5, 7) + '.',
      g.neueWoche ? el('span', { class: 'kw-unten', text: 'KW ' + g.kw }) : null)));
    const zellen = t => gruppen.map(g => {
      if (g.typ === 'ferien') return el('td', { class: 'ferien-sp' + (g.f.marke ? ' marke' : '') });
      const meine = g.spalten.filter(c => c.nutzbar && c.thema_id === t.id);
      const nutzbar = g.spalten.filter(c => c.nutzbar);
      const td = el('td', { class: 't tagzelle tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (nutzbar.length ? ' kann' : '') });
      if (nutzbar.length) {
        td.addEventListener('click', ev => blockMenue(ev, t, nutzbar));
        td.addEventListener('contextmenu', ev => blockMenue(ev, t, nutzbar));
      }
      if (meine.length) {
        td.appendChild(el('div', { class: 'segmente' }, g.spalten.map(c => el('span', {
          class: 'seg' + (c.nutzbar && c.thema_id === t.id ? ' an' : '') + (c.nutzbar ? '' : ' aus') }))));
        const m = istMarke(meine[meine.length - 1]);
        if (m) td.appendChild(m);
        td.title = t.titel + ': ' + meine.length + ' von ' + g.spalten.length + (g.spalten.length === 1 ? ' Block' : ' Blöcken') + ' am ' + L.tag(g.datum, true);
      }
      return td;
    });
    return el('table', { class: 'lp lp-tage' }, el('thead', {}, kopf), el('tbody', {}, zeilen(p, zellen)));
  }

  function rasterSchuljahr(p) {
    const jeWoche = {};
    p.bloecke.forEach(b => {
      const m = montagVon(b.datum);
      if (b.thema_id) (jeWoche[m + ':' + b.thema_id] = (jeWoche[m + ':' + b.thema_id] || 0) + 1);
    });
    const kopf = el('tr', {}, el('th', { class: 'links', text: 'Thema' }), p.wochen.map(w => el('th', {
      class: (w.heute ? 'heute' : '') + (w.frei ? ' ferien' : w.freie_tage ? ' teilfrei' : ''),
      title: (w.ferien ? w.ferien + (w.frei ? '' : ' (' + w.freie_tage + (w.freie_tage === 1 ? ' Tag' : ' Tage') + ' frei)') + ' · ' : '') + 'ab ' + L.tag(w.montag, true) },
    'KW', el('br'), String(w.kw))));
    const z = p.klasse_zeitraum || {};
    const ausserhalb = w => (z.ende && w.montag > z.ende) || (z.beginn && plusTage(w.montag, 4) < z.beginn);
    const zellen = t => p.wochen.map(w => {
      const n = jeWoche[w.montag + ':' + t.id] || 0;
      const td = el('td', { class: 't kw kann' + (w.heute ? ' heute' : '') + (w.frei ? ' ferien' : '') + (ausserhalb(w) ? ' aus' : ''),
        title: 'KW ' + w.kw + ': in den Doppelstunden zeigen' });
      td.addEventListener('click', () => { wahl.ansicht = 'bloecke'; wahl.springe = w.montag; zeichnen(); });
      if (n) {
        const davor = jeWoche[plusTage(w.montag, -7) + ':' + t.id];
        const danach = jeWoche[plusTage(w.montag, 7) + ':' + t.id];
        td.appendChild(el('span', { class: 'bal' + (davor ? '' : ' a') + (danach ? '' : ' e') }));
        td.appendChild(el('span', { class: 'anzahl', text: String(n) }));
        td.title = t.titel + ': ' + n + (n === 1 ? ' Block' : ' Blöcke') + ' in KW ' + w.kw + ' · antippen: in den Doppelstunden zeigen';
      }
      return td;
    });
    return el('table', { class: 'lp' }, el('thead', {}, kopf), el('tbody', {}, zeilen(p, zellen)));
  }

  function legende(p) {
    const lfs = [...new Set(p.themen.map(t => t.lernfeld_id).filter(Boolean))];
    return el('div', { class: 'legende' },
      lfs.map(id => el('span', {}, el('i', { class: 'farbe', style: 'background:' + lfFarbe(id) }), (p.lernfelder.find(l => l.id === id) || {}).nummer || '')),
      el('span', {}, el('i', { class: 'm-ferien' }), 'Ferien, Feiertag'),
      el('span', {}, el('i', { class: 'm-aus' }), 'Ausfall, vertreten, verschoben'),
      el('span', {}, el('b', { class: 'istm-l ok', text: '✓' }), 'gehalten'),
      el('span', {}, el('b', { class: 'istm-l mehr', text: '+1' }), '1 Block mehr'),
      el('span', {}, el('b', { class: 'istm-l fertig', text: '⊣' }), 'fertig'),
      el('span', {}, el('i', { class: 'istm-l offen' }), 'Ist fehlt'),
      el('span', {}, L.symbol('pin'), 'festgesetzt'),
      el('span', { class: 'leise', text: 'Tipp auf einen Block: Stunde öffnen oder festsetzen · Reihenfolge: Thema am Namen ziehen' }));
  }

  // Bilanz: je Lernfeld Stundenansatz gegen Verplantes und Gehaltenes, fuer den Strang Verplantes gegen Verfuegbares
  function bilanz(p) {
    const z = p.klasse_zeitraum || {};
    const ende = z.ende ? L.tag(z.ende, true) + ' (Ausschulung)' : L.tag(p.schuljahr.ende, true);
    const passt = p.summe.bedarf - p.summe.ueberlauf;
    return el('details', { class: 'karte bilanz', open: p.summe.ueberlauf ? true : null },
      el('summary', { class: 'zeile' }, L.symbol('diagramm' in L.SYMBOLE ? 'diagramm' : 'liste'), el('b', { text: 'Bilanz' }),
        el('span', { class: 'leise klein', text: 'noch ' + p.summe.rest + ' Blöcke bis ' + ende + ', verplant ' + p.summe.bedarf }),
        p.summe.ueberlauf ? el('span', { class: 'chip rot', text: p.summe.ueberlauf + ' Bl zu viel' }) : el('span', { class: 'chip gruen', text: 'passt' })),
      el('div', { class: 'rollbar', style: 'margin-top:10px' }, el('table', { class: 'liste' },
        el('thead', {}, el('tr', {}, ['Lernfeld', 'Stundenansatz', 'verplant', 'gehalten', 'passt nicht'].map(x => el('th', { text: x })))),
        el('tbody', {}, p.bilanz.map(b => el('tr', {},
          el('td', {}, el('b', { class: 'mono', text: b.nummer }), ' ', b.name),
          el('td', { class: 'mono', text: b.ansatz !== null ? b.ansatz + ' Bl' : '–' }),
          el('td', { class: 'mono' }, b.verplant + ' Bl',
            b.ansatz !== null && b.verplant !== b.ansatz ? el('span', { class: 'leise', text: ' (' + (b.verplant > b.ansatz ? '+' : '') + (b.verplant - b.ansatz) + ')' }) : null),
          el('td', { class: 'mono', text: b.gehalten + ' Bl' }),
          el('td', { class: 'mono', style: b.ueberlauf ? 'color:var(--rot);font-weight:700' : null, text: b.ueberlauf ? b.ueberlauf + ' Bl' : '–' })))))),
      el('p', { class: 'leise klein', style: 'margin-top:8px', text: 'Der Stundenansatz gilt für das ganze Lernfeld (1 Block = 2 Stunden). Teilen sich Gruppen oder Kolleginnen und Kollegen ein Lernfeld, ist die Abweichung nur ein Hinweis. ' + passt + ' von ' + p.summe.bedarf + ' verplanten Blöcken passen ins Schuljahr.' }));
  }

  function montagVon(iso) {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return isoVon(d);
  }
  function plusTage(iso, n) { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return isoVon(d); }
  function isoVon(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  // Tipp auf einen Block in der Zeile eines Themas: Stunde oeffnen, festsetzen bzw. Stecknadel loesen
  // c: ein Block oder eine Liste von Bloecken (Tagesansicht); Klick und Rechtsklick oeffnen dasselbe Menue
  function blockMenue(ev, t, c) {
    ev.preventDefault();
    const alt = document.getElementById('wp-menue');
    if (alt) alt.remove();
    const bloecke = (Array.isArray(c) ? c : [c]).filter(x => x.nutzbar);
    const punkte = [];
    if (t.pruefung_id) punkte.push(['pruefung', 'Prüfung öffnen (Termin dort ändern)', () => { location.hash = '#pruefung-' + t.pruefung_id; }]);
    else bloecke.forEach(b => punkte.push(['pin', (bloecke.length > 1 ? b.beginn + ': ' : '') + 'Hier festsetzen – beginnt ' + tagKurz(b.datum) + ' ' + b.beginn,
      () => festsetzen(t, b.datum, b.beginn)]));
    bloecke.forEach(b => punkte.push(['auge', 'Stunde öffnen: ' + tagKurz(b.datum) + ' ' + b.beginn, () => Stunde.oeffnen(b.datum, b.beginn, neuLaden)]));
    if (t.nadel && !t.pruefung_id) punkte.push(['undo', 'Stecknadel lösen (fließt wieder)', () => festsetzen(t, null, null)]);
    if (!t.pruefung_id) punkte.push(['stift', 'Thema bearbeiten …', () => themaBearbeiten(t)]);
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
