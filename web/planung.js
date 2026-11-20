'use strict';
// Unterrichtsplanung (Stufe C1, Voransichten A und C): Themenfolge je Strang (Klasse + Gruppe bzw. ganze Klasse) im
// Schuljahr, die Themen fliessen auf die Bloecke; Raster in den Ansichten Doppelstunden und Schuljahr; Bibliothek der
// Lernsituationen und Themen je Lernfeld mit "In Klasse uebernehmen".
const Planung = (() => {
  const el = L.el;
  const LF_FARBEN = ['#00639C', '#7b4fa8', '#8a9c00', '#d99000', '#0f8a8a', '#D4005E', '#5d6b7a', '#c2571a'];
  let ort = null;
  let P = null;                                  // Antwort von /api/planung
  const wahl = { schuljahr: null, klasse: null, gruppe: null, ansicht: 'schuljahr', bildungsgang: null, von: null };   // von: Kollegin (nur lesen)
  let ziehen = null;                             // Thema, das gerade in der Liste gezogen wird
  const auf = new Set();                         // Themen mit aufgeklappten Lernsituationen
  let gezeichnet = null;                         // Strang + Ansicht der letzten Zeichnung (Scrollstand halten)

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
    if (wahl.von) q.push('lehrkraft=' + wahl.von);
    try { P = await L.api('GET', '/api/planung' + (q.length ? '?' + q.join('&') : '')); }
    catch (e) {
      if (!wahl.von) throw e;
      L.meldung(e.message, true);   // z. B. Teilen inzwischen aus: zurueck zur eigenen Planung
      wahl.von = null;
      return laden();
    }
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
    wahl.von = null;
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

  const schl = c => c.datum + ' ' + c.beginn;

  // Eine Rasterzeile: welche Bloecke zu ihr gehoeren (passt), erster und letzter davon (Balkenenden)
  function reihe(p, t, passt, name, kopf) {
    const m = p.bloecke.filter(passt);
    return { t, passt, name, kopf, a: m.length ? schl(m[0]) : null, e: m.length ? schl(m[m.length - 1]) : null };
  }

  function aufZu(id) {
    if (auf.has(id)) auf.delete(id); else auf.add(id);
    zeichnen();
  }

  function titelZelle(t, i) {
    const ls = t.ls || [];
    const offen = auf.has(t.id);
    const zelle = el('td', { class: 'auf', title: t.titel + (ls.length ? ' · ' + ls.length + (ls.length === 1 ? ' Lernsituation' : ' Lernsituationen') : '') },
      t.pruefung_id ? el('span', { class: 'auf-knopf leer' })
        : el('button', { type: 'button', class: 'leicht auf-knopf', 'aria-expanded': offen ? 'true' : 'false',
          'aria-label': 'Lernsituationen ' + (offen ? 'zuklappen' : 'aufklappen'), onclick: ev => { ev.stopPropagation(); aufZu(t.id); } }, offen ? '▾' : '▸'),
      t.lernfeld ? el('span', { class: 'kz', style: 'color:' + lfFarbe(t.lernfeld_id), text: t.lernfeld }) : null,
      P.lesend ? el('span', { class: 'thema-name', text: t.titel })
        : el('button', { type: 'button', class: 'leicht thema-name', onclick: () => (t.pruefung_id ? (location.hash = '#pruefung-' + t.pruefung_id) : themaBearbeiten(t)) }, t.titel),
      t.pruefung_id ? el('span', { class: 'chip rot klein', text: 'Prüfung' }) : null,
      ls.length ? el('span', { class: 'ls-zahl', title: t.verteilt + ' von ' + t.bloecke + ' Blöcken auf Lernsituationen verteilt', text: ls.length + ' LS' }) : null,
      el('span', { class: 'art', title: ls.length ? 'Umfang des Themas (Budget) · ' + t.verteilt + ' Bl verteilt' : 'Umfang des Themas',
        text: ls.length ? t.verteilt + '/' + t.bloecke + ' Bl' : umfang(t.bloecke) }),
      t.verteilt > t.bloecke ? el('span', { class: 'chip gelb klein', title: 'Die Lernsituationen brauchen mehr als der geplante Umfang – das Thema wächst entsprechend.', text: '+' + (t.verteilt - t.bloecke) }) : null,
      t.ueberlauf ? el('span', { class: 'chip rot klein', title: 'Passt nicht mehr ins Schuljahr', text: '−' + t.ueberlauf }) : null,
      t.nadel === 'fehlt' ? el('span', { class: 'chip gelb klein', title: t.pruefung_id ? 'Zum Termin der Prüfung hast du keinen Unterricht in dieser Klasse – Termin unter Prüfungen ändern.'
        : 'Der festgesetzte Block findet nicht statt', text: t.pruefung_id ? 'kein Unterricht zum Termin' : 'Nadel?' }) : null);
    const tr = zelle;
    if (P.lesend) return zelle;
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

  function lsZelle(t, ls) {
    return el('td', { class: 'auf ls-auf', title: ls.titel + (ls.von ? ' · ' + tagKurz(ls.von) + (ls.bis !== ls.von ? ' bis ' + tagKurz(ls.bis) : '') : '') },
      P.lesend ? el('span', { class: 'thema-name ls-name', text: ls.titel })
        : el('button', { type: 'button', class: 'leicht thema-name ls-name', onclick: () => lsBearbeiten(t, ls) }, ls.titel),
      el('span', { class: 'art', title: 'geplant ' + umfang(ls.bloecke), text: umfang(ls.bedarf) }),
      ls.bedarf > ls.bloecke ? el('span', { class: 'chip gelb klein', title: 'Per Ist verlängert', text: '+' + (ls.bedarf - ls.bloecke) }) : null,
      ls.zugeteilt < ls.bedarf ? el('span', { class: 'chip rot klein', title: 'Passt nicht mehr ins Schuljahr', text: '−' + (ls.bedarf - ls.zugeteilt) }) : null);
  }

  // Zeilen: je Thema eine Zeile mit durchgehendem Balken; aufgeklappt darunter seine Lernsituationen,
  // der noch offene Rest des Umfangs und "+ Lernsituation"
  function zeilen(p, zellen) {
    const rows = [];
    p.themen.forEach((t, i) => {
      const farbe = '--b:' + (t.pruefung_id ? 'var(--rot)' : lfFarbe(t.lernfeld_id));
      rows.push(el('tr', { class: 'thema-zeile' + (auf.has(t.id) ? ' offen' : ''), style: farbe },
        titelZelle(t, i), zellen(reihe(p, t, c => c.thema_id === t.id, t.titel, true))));
      if (t.pruefung_id || !auf.has(t.id)) return;
      (t.ls || []).forEach(ls => rows.push(el('tr', { class: 'ls-zeile', style: farbe },
        lsZelle(t, ls), zellen(reihe(p, t, c => c.thema_id === t.id && c.ls_id === ls.id, ls.titel)))));
      if (t.ls.length && t.offen_rest > 0) {
        rows.push(el('tr', { class: 'ls-zeile offen-zeile', style: farbe },
          el('td', { class: 'auf ls-auf', title: 'Teil des Umfangs, der noch keiner Lernsituation gehört' },
            el('span', { class: 'ls-name leise', text: 'noch offen' }), el('span', { class: 'art', text: umfang(t.offen_rest) })),
          zellen(reihe(p, t, c => c.thema_id === t.id && !c.ls_id, t.titel + ' (noch offen)'))));
      }
      if (P.lesend) return;
      rows.push(el('tr', { class: 'ls-zeile neu-zeile' },
        el('td', { class: 'auf ls-auf' }, el('button', { type: 'button', class: 'leicht klein', onclick: () => lsBearbeiten(t, null) }, L.symbol('plus'), 'Lernsituation')),
        el('td', { colspan: 999 })));
    });
    if (P.lesend) return rows;
    // letzte Zeile: Block antippen -> Pruefung zu diesem Termin anlegen
    const planen = { id: 0, titel: 'Prüfung planen', planen: true };
    rows.push(el('tr', { class: 'pruef-zeile', style: '--b:var(--rot)' },
      el('td', { class: 'auf', title: 'Block antippen, um dort eine Prüfung anzulegen' },
        el('span', { class: 'auf-knopf leer' }), L.symbol('pruefung'), el('span', { class: 'pruef-text', text: 'Prüfung planen' }),
        el('span', { class: 'art', text: 'Block antippen' })),
      zellen(reihe(p, planen, () => false, planen.titel))));
    return rows;
  }

  // Kopfzelle der Themenspalte mit "alle auf-/zuklappen"
  function themenKopf(p, rowspan) {
    const kann = p.themen.filter(t => !t.pruefung_id);
    const alleAuf = kann.length && kann.every(t => auf.has(t.id));
    return el('th', { class: 'links', rowspan: rowspan || null }, 'Thema',
      kann.length ? el('button', { type: 'button', class: 'leicht klein alle-auf', title: 'Lernsituationen aller Themen ' + (alleAuf ? 'zuklappen' : 'aufklappen'),
        onclick: () => { kann.forEach(t => (alleAuf ? auf.delete(t.id) : auf.add(t.id))); zeichnen(); } }, alleAuf ? '▾ LS' : '▸ LS') : null);
  }

  // Montag der aktuellen Woche (am Wochenende: der kommenden)
  function aktuelleWoche(p) {
    const tag = new Date(p.heute + 'T12:00:00').getDay();
    const m = montagVon(p.heute);
    return tag === 0 || tag === 6 ? plusTage(m, 7) : m;
  }

  function zeichnen() {
    const teile = [];
    if (!P.schuljahre.length) {
      teile.push(el('div', { class: 'banner warnung', text: 'Es gibt noch kein Schuljahr. Der Admin legt es unter Grunddaten → Schuljahr und Ferien an (erster und letzter Unterrichtstag).' }));
      return L.setzen(ort, teile);
    }
    const sj = el('select', { 'aria-label': 'Schuljahr', style: 'width:auto', onchange: () => { wahl.schuljahr = Number(sj.value); wahl.klasse = null; neuLaden(); } },
      P.schuljahre.map(j => el('option', { value: j.id, text: 'Schuljahr ' + j.name, selected: j.id === P.schuljahr_id ? true : null })));
    const kopf = L.klassenReiter(P.straenge, wahl, (k, g) => { wahl.klasse = k; wahl.gruppe = g; neuLaden(); }, sj);
    const setzen = () => L.setzen(ort, kopf.reiter, el('div', { class: 'karteiblatt stapel' }, teile));
    if (!P.straenge.length) {
      teile.push(el('div', { class: 'banner' }, 'In diesem Schuljahr steht noch keine Klasse in deinem Stundenplan. ',
        el('a', { href: '#einstellungen', text: 'Stundenplan einrichten' })));
      return setzen();
    }
    const p = P.plan;
    const s = P.straenge.find(x => x.klasse_id === wahl.klasse && (x.gruppe_id || null) === (wahl.gruppe || null));
    if (P.lesend) {
      teile.push(el('div', { class: 'banner zeile' }, L.symbol('auge'),
        el('span', {}, 'Planung von ', el('b', { text: P.lesend.name }), ' · nur ansehen'),
        el('button', { type: 'button', class: 'klein rechts', onclick: () => { wahl.von = null; gezeichnet = null; neuLaden(); } }, L.symbol('zurueck' in L.SYMBOLE ? 'zurueck' : 'undo'), 'Zurück zu meiner Planung')));
    }
    teile.push(el('div', { class: 'zeile' },
      el('h2', { text: s ? s.klasse : '' }), kopf.unter,
      el('span', { class: 'leise klein', text: p.summe.bloecke + ' Blöcke im Schuljahr · noch ' + p.summe.rest + ' · ' + p.summe.bedarf + ' verplant · ' + p.summe.frei + ' frei' }),
      p.summe.ueberlauf ? el('span', { class: 'chip rot', text: p.summe.ueberlauf + ' Bl passen nicht mehr' }) : null,
      p.summe.ist_offen && !P.lesend ? el('span', { class: 'chip gelb', title: 'Gehaltene Stunden ohne Ist-Bestätigung' }, L.symbol('offen'), p.summe.ist_offen + ' ohne Ist') : null,
      p.spuren.length ? el('span', { class: 'chip', title: 'Diese Lernfelder haben eigene Blöcke im Stundenplan', text: 'eigene Blöcke: ' + p.spuren.map(x => x.nummer).join(', ') }) : null,
      s && s.gruppen && s.gruppen.length ? el('span', { class: 'chip gr', title: 'Gruppenstunden am selben Tag bekommen denselben Stoff und zählen zusammen als ein Schritt der Klasse. ' +
        p.summe.geteilt + ' Schritte im Schuljahr sind geteilt.', text: s.gruppen.join(' + ') + ' · ' + p.summe.geteilt + ' geteilt' }) : null,
      el('span', { class: 'rechts' },
        el('div', { class: 'segment', role: 'group', 'aria-label': 'Ansicht' },
          [['bloecke', 'Doppelstunden'], ['tage', 'Tage'], ['schuljahr', 'Schuljahr']].map(([a, t]) =>
            el('button', { type: 'button', class: wahl.ansicht === a ? 'an' : null, onclick: () => { wahl.ansicht = a; zeichnen(); } }, t))),
        P.lesend ? null : el('button', { type: 'button', onclick: () => themaBearbeiten(null) }, L.symbol('plus'), 'Thema'),
        P.lesend ? null : el('a', { class: 'knopf', href: '#planung-bibliothek' }, L.symbol('pakete'), 'Aus Bibliothek'))));
    if (!p.themen.length && P.lesend) {
      teile.push(el('div', { class: 'leer', text: P.lesend.name + ' hat für diese Klasse noch keine Themen geplant.' }));
    } else if (!p.themen.length) {
      teile.push(el('div', { class: 'leer' }, 'Noch keine Themen. Übernimm Lernsituationen aus der ',
        el('a', { href: '#planung-bibliothek', text: 'Bibliothek' }), ' oder lege mit „+ Thema“ eines an. Lernsituationen entwickelst du danach in den Themen.'));
    }
    if (P.lesend) teile.push(unterrichtKarte());
    const tabelle = wahl.ansicht === 'schuljahr' ? rasterSchuljahr(p) : wahl.ansicht === 'tage' ? rasterTage(p) : rasterBloecke(p);
    const scroll = el('div', { class: 'r-scroll' }, tabelle);
    const alt = ort.querySelector('.r-scroll');
    const altLinks = alt ? alt.scrollLeft : null;
    const stand = [wahl.schuljahr, wahl.klasse, wahl.gruppe, wahl.ansicht].join(':');
    const gleich = stand === gezeichnet && altLinks !== null && !wahl.springe;
    gezeichnet = stand;
    teile.push(scroll, legende(p), bilanz(p), kollegiumKarte());
    const y = window.scrollY;
    setzen();
    if (gleich) { scroll.scrollLeft = altLinks; window.scrollTo(0, y); return; }   // nach Aendern/Aufklappen an derselben Stelle bleiben
    const ziel = wahl.springe ? [...scroll.querySelectorAll('th[data-datum]')].find(th => th.dataset.datum >= wahl.springe) : null;
    wahl.springe = null;
    const heute = ziel || scroll.querySelector('th.diese-woche') || scroll.querySelector('th.ab-heute') || scroll.querySelector('th.heute');   // zur gewaehlten bzw. aktuellen Woche
    if (heute) scroll.scrollLeft = Math.max(0, heute.offsetLeft - 300 - 2 * heute.offsetWidth);
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
    const jetzt = aktuelleWoche(p);
    gruppen.forEach(g => {
      if (g.typ !== 'tag') return;
      g.dieseWoche = montagVon(g.datum) === jetzt;
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
    return (g.w2 ? ' w2' : '') + (g.neueWoche ? ' wochenstart' : '') + (g.dieseWoche ? ' diese-woche' : '');
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
    const kopf1 = el('tr', {}, themenKopf(p, 2), gruppen.map(g => g.typ === 'ferien' ? ferienKopf(g.f, 2)
      : el('th', { class: 'tag-kopf tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (g.abHeute ? ' ab-heute' : ''), colspan: g.spalten.length,
        'data-datum': g.datum },
        tagText(g.datum), g.neueWoche ? el('span', { class: 'kw', text: ' KW ' + g.kw }) : null)));
    const kopf2 = el('tr', {}, gruppen.map(g => g.typ === 'ferien' ? null : g.spalten.map((c, n) => el('th', {
      class: 'zeit' + (n === 0 ? ' tag-start' : '') + wochenKlasse(g) + (c.nutzbar ? '' : ' aus'),
      title: L.tag(c.datum, true) + ' ' + c.beginn + (c.gruppe ? ' · ' + c.gruppe + (c.zweit ? ' (gleicher Stoff wie die Gruppe davor)' : '') : '')
        + (c.nutzbar ? (c.art !== 'regulaer' ? ' · ' + (c.art === 'zusatz' ? 'Zusatzstunde' : 'verschoben') : '')
        : ' · ' + (c.zustand === 'ausfall' ? 'fällt aus' : c.zustand === 'vertreten' ? 'vertreten' : 'verschoben') + (c.grund ? ': ' + c.grund : '')) },
    c.beginn, c.gruppe ? el('span', { class: 'gr-kurz', text: c.gruppe }) : null))));
    const zellen = r => gruppen.map(g => g.typ === 'ferien' ? el('td', { class: 'ferien-sp' + (g.f.marke ? ' marke' : '') }) : g.spalten.map((c, n) => {
      const t = r.t;
      const td = el('td', { class: 't' + (n === 0 ? ' tag-start' : '') + wochenKlasse(g) + (c.datum === p.heute ? ' heute' : '') + (c.nutzbar ? ' kann' : ' aus') });
      if (!c.nutzbar) return td;
      if (r.passt(c)) {
        td.appendChild(el('span', { class: 'bal' + (schl(c) === r.a ? ' a' : '') + (schl(c) === r.e ? ' e' : '') }));
        if (r.kopf && c.teil === 1 && t.nadel === 'ok') td.appendChild(el('span', { class: 'nadel', title: 'festgesetzt' }, L.symbol('pin')));
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
    const kopf = el('tr', {}, themenKopf(p), gruppen.map(g => g.typ === 'ferien' ? ferienKopf(g.f)
      : el('th', { class: 'tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (g.abHeute ? ' ab-heute' : ''),
        title: L.tag(g.datum, true) + ' · ' + g.spalten.length + (g.spalten.length === 1 ? ' Block' : ' Blöcke') },
      L.TAGE[new Date(g.datum + 'T12:00:00').getDay()], el('br'), g.datum.slice(8, 10) + '.' + g.datum.slice(5, 7) + '.',
      g.neueWoche ? el('span', { class: 'kw-unten', text: 'KW ' + g.kw }) : null)));
    const zellen = r => gruppen.map(g => {
      const t = r.t;
      if (g.typ === 'ferien') return el('td', { class: 'ferien-sp' + (g.f.marke ? ' marke' : '') });
      const meine = g.spalten.filter(c => c.nutzbar && r.passt(c));
      const nutzbar = g.spalten.filter(c => c.nutzbar);
      const td = el('td', { class: 't tagzelle tag-start' + wochenKlasse(g) + (g.datum === p.heute ? ' heute' : '') + (nutzbar.length ? ' kann' : '') });
      if (nutzbar.length) {
        td.addEventListener('click', ev => blockMenue(ev, t, nutzbar));
        td.addEventListener('contextmenu', ev => blockMenue(ev, t, nutzbar));
      }
      if (meine.length) {
        td.appendChild(el('div', { class: 'segmente' }, g.spalten.map(c => el('span', {
          class: 'seg' + (c.nutzbar && r.passt(c) ? ' an' : '') + (c.nutzbar ? '' : ' aus') }))));
        const m = istMarke(meine[meine.length - 1]);
        if (m) td.appendChild(m);
        td.title = r.name + ': ' + meine.length + ' von ' + g.spalten.length + (g.spalten.length === 1 ? ' Block' : ' Blöcken') + ' am ' + L.tag(g.datum, true);
      }
      return td;
    });
    return el('table', { class: 'lp lp-tage' }, el('thead', {}, kopf), el('tbody', {}, zeilen(p, zellen)));
  }

  function rasterSchuljahr(p) {
    const jetzt = aktuelleWoche(p);
    const kopf = el('tr', {}, themenKopf(p), p.wochen.map(w => el('th', {
      class: (w.montag === jetzt ? 'diese-woche' : '') + (w.frei ? ' ferien' : w.freie_tage ? ' teilfrei' : ''), 'data-datum': w.montag,
      title: (w.ferien ? w.ferien + (w.frei ? '' : ' (' + w.freie_tage + (w.freie_tage === 1 ? ' Tag' : ' Tage') + ' frei)') + ' · ' : '') + 'ab ' + L.tag(w.montag, true) },
    'KW', el('br'), String(w.kw))));
    const z = p.klasse_zeitraum || {};
    const ausserhalb = w => (z.ende && w.montag > z.ende) || (z.beginn && plusTage(w.montag, 4) < z.beginn);
    const zellen = r => {
      const jeWoche = {};
      p.bloecke.forEach(b => { if (!b.zweit && r.passt(b)) { const m = montagVon(b.datum); jeWoche[m] = (jeWoche[m] || 0) + 1; } });
      return p.wochen.map(w => {
      const n = jeWoche[w.montag] || 0;
      const td = el('td', { class: 't kw kann' + (w.montag === jetzt ? ' diese-woche' : '') + (w.frei ? ' ferien' : '') + (ausserhalb(w) ? ' aus' : ''),
        title: 'KW ' + w.kw + ': in den Doppelstunden zeigen' });
      td.addEventListener('click', () => { wahl.ansicht = 'bloecke'; wahl.springe = w.montag; zeichnen(); });
      if (n) {
        const davor = jeWoche[plusTage(w.montag, -7)];
        const danach = jeWoche[plusTage(w.montag, 7)];
        td.appendChild(el('span', { class: 'bal' + (davor ? '' : ' a') + (danach ? '' : ' e') }));
        td.appendChild(el('span', { class: 'anzahl', text: String(n) }));
        td.title = r.name + ': ' + n + (n === 1 ? ' Block' : ' Blöcke') + ' in KW ' + w.kw + ' · antippen: in den Doppelstunden zeigen';
      }
      return td;
      });
    };
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
      el('span', {}, el('i', { class: 'm-woche' }), 'aktuelle Woche'),
      el('span', { class: 'leise', text: '▸ zeigt die Lernsituationen eines Themas · Tipp auf einen Block: Stunde öffnen oder festsetzen · Reihenfolge: Thema am Namen ziehen' }));
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

  // Stufe E: Klassenansicht "Kollegium": wer die Klasse noch unterrichtet (deren Planung ansehen) und die geteilten
  // Termine der naechsten Wochen. Nur, wenn der Admin das Teilen eingeschaltet hat.
  function kollegiumKarte() {
    const k = P.kollegium;
    if (!k || P.lesend) return null;
    const andere = k.lehrkraefte.filter(l => !l.ich);
    return el('div', { class: 'karte stapel kollegium' },
      el('h3', {}, L.symbol('klassen'), ' Kollegium dieser Klasse'),
      andere.length ? el('div', { class: 'stapel', style: 'gap:6px' }, andere.map(l => el('div', { class: 'zeile' },
        el('span', { text: l.name }),
        el('button', { type: 'button', class: 'klein rechts', onclick: () => { wahl.von = l.id; gezeichnet = null; neuLaden(); window.scrollTo(0, 0); } },
          L.symbol('auge'), 'Planung ansehen'))))
        : el('p', { class: 'leise klein', text: 'Außer dir unterrichtet laut Stundenplan niemand diese Klasse.' }),
      el('h4', { text: 'Geteilte Termine der nächsten ' + Math.round(k.tage / 7) + ' Wochen' }),
      k.termine.length ? el('div', { class: 'stapel', style: 'gap:4px' }, k.termine.map(t => el('div', { class: 'zeile' },
        el('span', { class: 'mono klein', text: tagKurz(t.datum) + (t.bis ? '–' + tagKurz(t.bis) : '') + (t.beginn ? ' ' + t.beginn : '') }),
        el('span', { text: t.titel }), el('span', { class: 'leise klein', text: t.fremd ? 'von ' + t.von_name : 'von dir' }))))
        : el('p', { class: 'leise klein', text: 'Keine.' }),
      el('p', { class: 'leise klein', text: 'Einen Termin teilst du im Wochenplan: Termin mit dieser Klasse und dem Haken „für die Lehrkräfte der Klasse sichtbar“. ' +
        'Den Unterrichtsinhalt deiner Stunden sehen sie in deiner Planung, Notizen nur mit dem Haken in der Stunde. Noten bleiben immer privat; die Schülerliste der Klasse nutzt ihr ohnehin gemeinsam.' }));
  }

  // Stufe E, lesende Planung: was in den gehaltenen Stunden dran war (Unterrichtsinhalt, geteilte Notizen), neueste zuerst
  function unterrichtKarte() {
    const u = P.unterricht || [];
    const zeile = e => el('div', { class: 'stapel unterricht-eintrag', style: 'gap:2px' },
      el('div', { class: 'zeile' },
        el('span', { class: 'mono klein', text: tagKurz(e.datum) + ' ' + e.beginn + (e.gruppe ? ' · ' + e.gruppe : '') }),
        e.thema ? el('span', { class: 'leise klein', text: e.thema }) : null),
      e.inhalt ? el('p', { class: 'vorzeilen', text: e.inhalt }) : null,
      e.notizen ? el('p', { class: 'klein hinweis-text vorzeilen' }, el('b', { text: 'Notiz: ' }), e.notizen) : null);
    const erste = u.slice(0, 3), rest = u.slice(3);
    return el('div', { class: 'karte stapel kollegium' },
      el('h3', {}, L.symbol('stift'), ' Unterricht von ' + P.lesend.name),
      u.length ? el('div', { class: 'stapel', style: 'gap:10px' }, erste.map(zeile)) :
        el('p', { class: 'leise klein', text: 'Noch keine Unterrichtsinhalte eingetragen.' }),
      rest.length ? el('details', {}, el('summary', { class: 'klein', text: 'Ältere Stunden (' + rest.length + ')' }),
        el('div', { class: 'stapel', style: 'gap:10px;margin-top:8px' }, rest.map(zeile))) : null,
      el('p', { class: 'leise klein', text: 'Unterrichtsinhalt wie fürs Klassenbuch. Notizen nur, wenn ' + P.lesend.name + ' sie in der Stunde fürs Kollegium freigegeben hat.' }));
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
    if (P.lesend) return;   // fremde Planung: nur ansehen
    const alt = document.getElementById('wp-menue');
    if (alt) alt.remove();
    const bloecke = (Array.isArray(c) ? c : [c]).filter(x => x.nutzbar);
    const punkte = [];
    const anlegen = b => () => Pruefungen.ausWochenplan({ klasse: { id: wahl.klasse }, gruppe: b.gruppe_id ? { id: b.gruppe_id } : null, datum: b.datum, beginn: b.beginn },
      () => { gezeichnet = null; wahl.springe = b.datum; neuLaden(); });
    if (t.planen) {
      bloecke.forEach(b => punkte.push(['pruefung', 'Prüfung hier anlegen: ' + tagKurz(b.datum) + ' ' + b.beginn + (b.gruppe ? ' · ' + b.gruppe : '') + ' …', anlegen(b)]));
      bloecke.forEach(b => punkte.push(['auge', 'Stunde öffnen: ' + tagKurz(b.datum) + ' ' + b.beginn, () => Stunde.oeffnen(b.datum, b.beginn, neuLaden)]));
      if (!bloecke.length) return;
    } else if (t.pruefung_id) punkte.push(['pruefung', 'Prüfung öffnen (Termin dort ändern)', () => { location.hash = '#pruefung-' + t.pruefung_id; }]);
    else bloecke.forEach(b => punkte.push(['pin', (bloecke.length > 1 ? b.beginn + ': ' : '') + 'Hier festsetzen – beginnt ' + tagKurz(b.datum) + ' ' + b.beginn,
      () => festsetzen(t, b.datum, b.beginn)]));
    bloecke.forEach(b => punkte.push(['auge', 'Stunde öffnen: ' + tagKurz(b.datum) + ' ' + b.beginn, () => Stunde.oeffnen(b.datum, b.beginn, neuLaden)]));
    if (t.nadel && !t.pruefung_id) punkte.push(['undo', 'Stecknadel lösen (fließt wieder)', () => festsetzen(t, null, null)]);
    if (!t.pruefung_id && !t.planen) {
      punkte.push(['stift', 'Thema bearbeiten …', () => themaBearbeiten(t)]);
      bloecke.forEach(b => punkte.push(['pruefung', 'Prüfung hier anlegen: ' + tagKurz(b.datum) + ' ' + b.beginn + ' …', anlegen(b)]));
    }
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
    const strang = P.straenge.find(x => x.klasse_id === wahl.klasse) || {};
    // fehlendes Lernfeld gleich hier anlegen und auswaehlen
    const lfNeu = Lernfelder.knopf(strang.bildungsgang_id, r => {
      const b = r.bildungsgaenge.find(x => x.id === strang.bildungsgang_id);
      const neu = b && b.lernfelder.find(x => x.id === r.id);
      if (neu) lf.appendChild(el('option', { value: neu.id, text: neu.nummer + ' ' + neu.name, selected: true }));
      lf.value = String(r.id);
    }, 'Lernfeld anlegen');
    const hinweis = el('textarea', { maxlength: 4000, rows: 3, placeholder: 'Lehrstoff, Material, Hinweise (für „Lehrstoff kopieren“ in Stufe C2)' });
    hinweis.value = t ? t.hinweis : '';
    const weitere = t ? [
      { text: 'Entfernen', klasse: 'warnen', speichern: () => L.api('POST', '/api/thema/' + t.id + '/loeschen', {}) },
    ] : [];
    const r = await L.dialog({
      titel: t ? 'Thema' : 'Neues Thema', weitere,
      inhalt: el('div', { class: 'felder' },
        L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Umfang in Blöcken', bloecke, '1 Block = 1 Doppelstunde · Rahmen für die Lernsituationen'),
          el('div', { class: 'stapel', style: 'gap:2px' }, L.feld('Lernfeld', lf), el('div', {}, lfNeu))),
        t && t.ls.length ? el('p', { class: 'leise klein', text: t.ls.length + (t.ls.length === 1 ? ' Lernsituation' : ' Lernsituationen') + ' mit ' + umfang(t.verteilt)
          + (t.verteilt > t.bloecke ? ' – mehr als der Umfang, das Thema wächst auf ' + umfang(t.verteilt) + '.' : t.verteilt < t.bloecke ? ' · noch offen ' + umfang(t.bloecke - t.verteilt) + '.' : ' · Umfang ganz verteilt.') }) : null,
        L.feld('Hinweis', hinweis),
        t ? el('div', { class: 'zeile' },
          L.nebenknopf('↑ nach oben', () => schieben(t, -1), 'klein'),
          L.nebenknopf('↓ nach unten', () => schieben(t, 1), 'klein'),
          t.von ? el('span', { class: 'leise klein', text: 'läuft ' + tagKurz(t.von) + (t.bis !== t.von ? ' bis ' + tagKurz(t.bis) : '') }) : null) : null),
      speichern: () => L.api('POST', t ? '/api/thema/' + t.id : '/api/thema', {
        klasse_id: wahl.klasse, gruppe_id: wahl.gruppe, schuljahr_id: wahl.schuljahr,
        titel: titel.value, bloecke: Number(bloecke.value), lernfeld_id: lf.value || null, hinweis: hinweis.value }),
    });
    if (r) await neuLaden();
  }

  // Lernsituation in einem Thema der Planung anlegen bzw. aendern (auch in ein anderes Thema verschieben)
  async function lsBearbeiten(t, ls) {
    const p = P.plan;
    const rest = t.bloecke - t.verteilt;
    const titel = el('input', { maxlength: 200, value: ls ? ls.titel : '', placeholder: 'z. B. Förderanlage automatisieren' });
    const bloecke = el('input', { type: 'number', min: 1, max: 400, value: ls ? ls.bloecke : (rest > 0 ? rest : 2), style: 'width:110px' });
    const thema = el('select', {}, p.themen.filter(x => !x.pruefung_id).map(x => el('option', { value: x.id, text: x.titel, selected: x.id === t.id ? true : null })));
    const hinweis = el('textarea', { maxlength: 4000, rows: 3, placeholder: 'Lehrstoff, Material, Hinweise' });
    hinweis.value = ls ? ls.hinweis : '';
    const weitere = ls ? [
      { text: 'Entfernen', klasse: 'warnen', speichern: () => L.api('POST', '/api/ls/' + ls.id + '/loeschen', {}) },
      { text: '↑', speichern: () => L.api('POST', '/api/ls/' + ls.id + '/schieben', { richtung: -1 }) },
      { text: '↓', speichern: () => L.api('POST', '/api/ls/' + ls.id + '/schieben', { richtung: 1 }) },
    ] : [];
    const r = await L.dialog({
      titel: ls ? 'Lernsituation' : 'Neue Lernsituation', weitere,
      inhalt: el('div', { class: 'felder' },
        el('p', { class: 'leise klein', text: 'Thema „' + t.titel + '“ · Umfang ' + umfang(t.bloecke) + (t.ls.length ? ', davon verteilt ' + umfang(t.verteilt) : '') }),
        L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Umfang in Blöcken', bloecke, rest > 0 && !ls ? 'Im Thema sind noch ' + umfang(rest) + ' offen' : 'Mehr als der Umfang lässt das Thema wachsen'),
          ls ? L.feld('Gehört zum Thema', thema) : null),
        L.feld('Hinweis', hinweis),
        ls && ls.von ? el('p', { class: 'leise klein', text: 'läuft ' + tagKurz(ls.von) + (ls.bis !== ls.von ? ' bis ' + tagKurz(ls.bis) : '') }) : null),
      speichern: () => L.api('POST', ls ? '/api/ls/' + ls.id : '/api/ls', {
        thema_id: ls ? Number(thema.value) : t.id, titel: titel.value, bloecke: Number(bloecke.value), hinweis: hinweis.value }),
    });
    if (r) { auf.add(ls ? Number(thema.value) : t.id); await neuLaden(); }
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
    teile.push(el('p', { class: 'leise', style: 'max-width:80ch', text: 'Themen je ' + (bg.einheit === 'modul' ? 'Modul' : 'Lernfeld') +
      ' mit ihrem Umfang, darin die Lernsituationen – für alle im Bildungsgang sichtbar. Ändern darf, wer etwas angelegt hat. „In Klasse übernehmen“ kopiert das Thema samt Lernsituationen in deine Planung; dort kannst du alles anpassen, ohne die Bibliothek zu verändern.' }));
    const einheit = bg.einheit === 'modul' ? 'Modul' : 'Lernfeld';
    teile.push(el('div', { class: 'zeile' }, el('span', { class: 'leise klein', text: 'Fehlt ein ' + einheit + '?' }),
      Lernfelder.knopf(bg.id, () => bibliothekZeigen(), einheit + ' anlegen')));
    if (!B.lernfelder.length) teile.push(el('div', { class: 'leer', text: 'In diesem Bildungsgang gibt es noch keine ' + (bg.einheit === 'modul' ? 'Module' : 'Lernfelder') + '. Lege mit „' + einheit + ' anlegen“ eines an oder bitte den Admin darum.' }));
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
    const summe = lf.themen.reduce((n, t) => n + Math.max(t.bloecke, t.verteilt), 0);
    return el('details', { class: 'karte lf-karte', open: lf.themen.length ? true : null },
      el('summary', { class: 'zeile' }, el('b', { class: 'mono', text: lf.nummer }), el('b', { text: lf.name }),
        el('span', { class: 'leise klein', text: lf.stunden ? lf.stunden + ' Std = ' + Math.round(lf.stunden / 2) + ' Bl' : 'ohne Stundenansatz' }),
        summe ? el('span', { class: 'chip', title: 'Summe der Themen', text: summe + ' Bl in der Bibliothek' }) : null),
      el('div', { class: 'stapel', style: 'gap:10px;margin-top:10px' },
        lf.themen.map(t => themaKarte(lf, t)),
        el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'klein', onclick: () => bausteinBearbeiten(lf, null, 'thema') }, L.symbol('plus'), 'Neues Thema'))));
  }

  function themaKarte(lf, t) {
    const rest = t.bloecke - t.verteilt;
    const n = t.lernsituationen.length;
    return el('div', { class: 'ka' },
      el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: 'Thema' }), el('b', { text: t.titel }),
        el('span', { class: 'leise klein', text: umfang(t.bloecke) + (n ? ' · ' + t.verteilt + ' Bl in ' + n + ' LS' : '') }),
        n && rest > 0 ? el('span', { class: 'chip klein', text: 'noch ' + rest + ' Bl offen' }) : null,
        rest < 0 ? el('span', { class: 'chip gelb klein', title: 'Die Lernsituationen brauchen mehr als der Umfang', text: '+' + (-rest) + ' Bl' }) : null,
        el('span', { class: 'rechts' },
          darf(t) ? el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Thema bearbeiten', onclick: () => bausteinBearbeiten(lf, t, 'thema') }, L.symbol('stift')) : null,
          el('button', { type: 'button', class: 'klein', onclick: () => uebernehmen(lf, t) }, L.symbol('plus'), 'In Klasse übernehmen'))),
      n ? el('table', { class: 'liste' }, el('tbody', {}, t.lernsituationen.map(ls => el('tr', {},
        el('td', {}, el('span', { class: 'chip klein', text: 'LS' }), ' ', ls.titel),
        el('td', { class: 'leise klein', text: ls.hinweis ? ls.hinweis.split('\n')[0].slice(0, 60) : '' }),
        el('td', { class: 'mono', style: 'text-align:right;white-space:nowrap', text: umfang(ls.bloecke) }),
        el('td', { class: 'knoepfe' },
          darf(ls) ? el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Lernsituation bearbeiten', onclick: () => bausteinBearbeiten(lf, ls, 'ls', t) }, L.symbol('stift')) : null,
          el('button', { type: 'button', class: 'leicht klein', title: 'Nur diese Lernsituation in ein Thema deiner Planung übernehmen', onclick: () => uebernehmen(lf, ls, t) }, L.symbol('plus'), 'Klasse'))))))
        : el('p', { class: 'leise klein', text: 'Noch keine Lernsituationen. Das Thema fließt in der Klasse mit seinem Umfang von ' + umfang(t.bloecke) + '.' }),
      el('div', { class: 'zeile leise klein' },
        el('button', { type: 'button', class: 'leicht klein', onclick: () => bausteinBearbeiten(lf, null, 'ls', t) }, L.symbol('plus'), 'Lernsituation'),
        el('span', { text: 'angelegt von ' + (t.besitzer_id === konto.id ? 'dir' : t.besitzer || '–') + (t.genutzt.length ? ' · genutzt in ' + t.genutzt.join(', ') : '') })));
  }

  async function bausteinBearbeiten(lf, b, art, thema) {
    const titel = el('input', { maxlength: 200, value: b ? b.titel : '', placeholder: art === 'ls' ? 'z. B. Förderanlage automatisieren' : 'z. B. SPS-Grundlagen' });
    const bloecke = el('input', { type: 'number', min: 1, max: 400, value: b ? b.bloecke : (art === 'ls' ? 2 : 4), style: 'width:110px' });
    const hinweis = el('textarea', { maxlength: 4000, rows: 3, placeholder: 'Lehrstoff, Material, Hinweise' });
    hinweis.value = b ? b.hinweis : '';
    const weitere = [];
    if (b) {
      weitere.push({ text: 'Löschen', klasse: 'warnen', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/loeschen', {}) });
      weitere.push({ text: '↑', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/schieben', { richtung: -1 }) });
      weitere.push({ text: '↓', speichern: () => L.api('POST', '/api/baustein/' + b.id + '/schieben', { richtung: 1 }) });
    }
    const kinder = b && b.lernsituationen ? b.lernsituationen.length : 0;
    const r = await L.dialog({
      titel: (b ? '' : 'Neue ') + (art === 'ls' ? 'Lernsituation' : 'Thema') + ' · ' + lf.nummer, weitere,
      inhalt: el('div', { class: 'felder' },
        thema ? el('p', { class: 'leise klein', text: 'im Thema „' + thema.titel + '“ (' + umfang(thema.bloecke) + ', verteilt ' + umfang(thema.verteilt) + ')' }) : null,
        L.feld('Titel', titel),
        L.feld('Umfang in Blöcken', bloecke, art === 'ls' ? '1 Block = 1 Doppelstunde' : '1 Block = 1 Doppelstunde · Rahmen für die Lernsituationen'),
        L.feld('Hinweis', hinweis),
        kinder ? el('p', { class: 'leise klein', text: 'Löschen entfernt auch die ' + kinder + (kinder === 1 ? ' Lernsituation' : ' Lernsituationen') + ' dieses Themas. Übernommene Planungen behalten ihre Kopie.' }) : null),
      speichern: () => L.api('POST', b ? '/api/baustein/' + b.id : '/api/baustein', { art, lernfeld_id: lf.id, eltern_id: thema ? thema.id : null,
        titel: titel.value, bloecke: Number(bloecke.value), hinweis: hinweis.value }),
    });
    if (r) await bibliothekZeigen();
  }

  // Thema (samt Lernsituationen) in einen Strang kopieren; eine einzelne Lernsituation (eltern = ihr Bibliotheks-Thema)
  // kommt in ein vorhandenes Thema der gewaehlten Klasse
  async function uebernehmen(lf, b, eltern) {
    let pl;
    try { pl = await L.api('GET', '/api/planung' + (wahl.schuljahr ? '?schuljahr=' + wahl.schuljahr : '')); } catch (e) { L.meldung(e.message, true); return; }
    const passend = pl.straenge.filter(s => s.bildungsgang_id === B.bildungsgang_id);
    if (!pl.schuljahre.length) { L.meldung('Es gibt noch kein Schuljahr (legt der Admin an).', true); return; }
    if (!passend.length) { L.meldung('Du hast in diesem Schuljahr keine Klasse dieses Bildungsgangs im Stundenplan.', true); return; }
    const ls = b.art === 'ls';
    const vorher = passend.find(s => s.klasse_id === wahl.klasse && (s.gruppe_id || null) === (wahl.gruppe || null)) || passend[0];
    const strang = el('select', {}, passend.map(s => el('option', { value: strangKey(s), text: s.name, selected: s === vorher ? true : null })));
    const thema = el('select', {});
    const themaHinweis = el('p', { class: 'leise klein' });
    async function themenLaden() {
      const s = passend.find(x => strangKey(x) === strang.value);
      L.setzen(thema);
      try {
        const x = await L.api('GET', '/api/planung?schuljahr=' + pl.schuljahr_id + '&klasse=' + s.klasse_id + (s.gruppe_id ? '&gruppe=' + s.gruppe_id : ''));
        const themen = ((x.plan || {}).themen || []).filter(t => !t.pruefung_id);
        const gleich = themen.find(t => t.baustein_id === (eltern || {}).id);
        L.setzen(thema, themen.map(t => el('option', { value: t.id, text: t.titel + ' · ' + umfang(t.bloecke), selected: t === gleich ? true : null })));
        themaHinweis.textContent = themen.length ? '' : 'In dieser Klasse gibt es noch kein Thema. Übernimm zuerst das Thema „' + eltern.titel + '“ oder lege eines an.';
      } catch (e) { themaHinweis.textContent = e.message; }
    }
    if (ls) { strang.addEventListener('change', themenLaden); await themenLaden(); }
    const kinder = b.lernsituationen ? b.lernsituationen.length : 0;
    const r = await L.dialog({
      titel: ls ? 'Lernsituation übernehmen' : 'Thema in Klasse übernehmen', knopf: 'Übernehmen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('p', { class: 'klein' }, el('b', { text: b.titel }), ' · ' + umfang(b.bloecke) + (kinder ? ' mit ' + kinder + (kinder === 1 ? ' Lernsituation' : ' Lernsituationen') : '')),
        L.feld('Klasse bzw. Gruppe · Schuljahr ' + (pl.schuljahre.find(j => j.id === pl.schuljahr_id) || {}).name, strang),
        ls ? L.feld('In das Thema', thema) : null, ls ? themaHinweis : null,
        el('p', { class: 'leise klein', text: ls ? 'Kommt ans Ende der Lernsituationen dieses Themas.' : 'Kommt ans Ende der Themenfolge. Die Reihenfolge änderst du in der Planung.' })),
      speichern: () => {
        const s = passend.find(x => strangKey(x) === strang.value);
        return L.api('POST', '/api/planung/uebernehmen', { klasse_id: s.klasse_id, gruppe_id: s.gruppe_id, schuljahr_id: pl.schuljahr_id, baustein_id: b.id,
          thema_id: ls ? Number(thema.value) || null : null }).then(x => ({ ...x, s }));
      },
    });
    if (!r) return;
    wahl.schuljahr = pl.schuljahr_id; wahl.klasse = r.s.klasse_id; wahl.gruppe = r.s.gruppe_id;
    L.meldung('„' + b.titel + '“' + (!ls && r.id ? ' mit ' + r.id + (r.id === 1 ? ' Lernsituation' : ' Lernsituationen') : '') + ' in ' + r.s.name + ' übernommen.');
    await bibliothekZeigen();
  }

  return { zeigen };
})();
