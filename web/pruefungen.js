'use strict';
// Pruefungen und Bewertung (Stufe D1). Reiter: Pruefungen · Schuelerlisten · Vorlagen · Notenschluessel.
// Eine Pruefung: fester Termin (belegt Bloecke der Planung) oder Fenster mit Frist; Erfassung als Punkte je Aufgabe,
// Gesamtpunkte oder Feedbackbogen (je Schueler im Overlay). Jede Eingabe wird sofort gespeichert; Note und Rechenweg
// rechnet der Server ueber den gueltigen Notenschluessel.
const Pruefungen = (() => {
  const el = L.el;
  const ARTEN = [['schriftlich', 'schriftlich'], ['muendlich', 'mündlich'], ['praktisch', 'praktisch'], ['portfolio', 'Portfolio']];
  const STAND = { geplant: ['geplant', ''], angekuendigt: ['angekündigt', 'blau'], durchgefuehrt: ['durchgeführt', 'gelb'], ausgewertet: ['abgeschlossen', 'gruen'] };
  const ERFASSUNG = { aufgaben: 'Punkte je Aufgabe', gesamt: 'Gesamtpunkte', bogen: 'Feedbackbogen' };
  const wahl = { schuljahr: null, klasse: null, gruppe: null };
  let ort = null;
  let G = null;   // Grunddaten (Lernfelder, Zeitraster, Schuljahre)

  const fmt = (z, stellen = 1) => z === null || z === undefined ? '–' : (Math.abs(z - Math.round(z)) < 1e-9 ? String(Math.round(z)) : z.toFixed(stellen).replace('.', ','));
  const tagKurz = iso => L.tag(iso).trim();

  async function grunddaten() {
    if (!G) G = await L.api('GET', '/api/grunddaten');
    return G;
  }

  // Bloecke der Klasse laut Zeitraster ihres Bildungsgangs
  function bloeckeDerKlasse(kid) {
    const k = G.klassen.find(x => x.id === kid);
    const b = k ? G.bildungsgaenge.find(x => x.id === k.bildungsgang_id) : null;
    return b && b.zeitraster.length ? b.zeitraster : G.zeitraster_schule;
  }

  function lernfelderDerKlasse(kid) {
    const k = G.klassen.find(x => x.id === kid);
    const b = k ? G.bildungsgaenge.find(x => x.id === k.bildungsgang_id) : null;
    return b ? b.lernfelder : [];
  }

  async function zeigen(ortEl, teil) {
    ort = ortEl;
    await grunddaten();
    if (teil && teil.startsWith('pruefung-')) return detailZeigen(Number(teil.slice(9)));
    if (teil === 'schueler') return schuelerZeigen();
    if (teil === 'vorlagen') return vorlagenZeigen();
    if (teil === 'schluessel') return schluesselZeigen();
    return listeZeigen();
  }

  // --- Strangwahl (Klasse bzw. Gruppe im Schuljahr), wie in der Planung ---

  async function strangLaden() {
    const P = await L.api('GET', '/api/planung' + (wahl.schuljahr ? '?schuljahr=' + wahl.schuljahr : ''));
    wahl.schuljahr = P.schuljahr_id;
    if (!P.straenge.some(s => s.klasse_id === wahl.klasse && (s.gruppe_id || null) === (wahl.gruppe || null)) && P.straenge.length) {
      wahl.klasse = P.straenge[0].klasse_id;
      wahl.gruppe = P.straenge[0].gruppe_id;
    }
    return P;
  }

  // Karteireiter je Klasse (Gruppen als Wahl darunter), Schuljahr rechts
  function strangKopf(P, neu) {
    const sj = el('select', { 'aria-label': 'Schuljahr', style: 'width:auto', onchange: () => { wahl.schuljahr = Number(sj.value); wahl.klasse = null; neu(); } },
      P.schuljahre.map(j => el('option', { value: j.id, text: 'Schuljahr ' + j.name, selected: j.id === P.schuljahr_id ? true : null })));
    return L.klassenReiter(P.straenge.map(s => Object.assign({}, s, { themen: 0 })), wahl, (k, g) => { wahl.klasse = k; wahl.gruppe = g; neu(); }, sj);
  }

  // --- Liste der Pruefungen ---

  async function listeZeigen() {
    const P = await strangLaden();
    if (!P.schuljahre.length) return L.setzen(ort, el('div', { class: 'banner warnung', text: 'Es gibt noch kein Schuljahr. Der Admin legt es unter Grunddaten an.' }));
    const kopf = strangKopf(P, listeZeigen);
    if (!P.straenge.length) return L.setzen(ort, kopf.reiter, el('div', { class: 'karteiblatt' }, el('div', { class: 'banner' }, 'In diesem Schuljahr steht noch keine Klasse in deinem Stundenplan. ', el('a', { href: '#einstellungen', text: 'Stundenplan einrichten' }))));
    const R = await L.api('GET', '/api/pruefungen?schuljahr=' + wahl.schuljahr + '&klasse=' + wahl.klasse + (wahl.gruppe ? '&gruppe=' + wahl.gruppe : ''));
    const s = P.straenge.find(x => x.klasse_id === wahl.klasse && (x.gruppe_id || null) === (wahl.gruppe || null));
    L.setzen(ort, kopf.reiter, el('div', { class: 'karteiblatt stapel' },
      el('div', { class: 'zeile' }, el('h2', { text: s ? s.klasse : '' }), kopf.unter,
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt', onclick: () => pruefungDialog(null, R, { klasse_id: wahl.klasse, gruppe_id: wahl.gruppe, schuljahr_id: wahl.schuljahr }) }, L.symbol('plus'), 'Prüfung'))),
      R.pruefungen.length ? el('div', { class: 'raster' }, R.pruefungen.map(p => pruefungKarte(p)))
        : el('div', { class: 'leer', text: 'Noch keine Prüfung. Lege eine mit „+ Prüfung“ an oder im Wochenplan über das Menü einer Stunde.' })));
  }

  function wannText(p) {
    const umfang = p.bloecke > 1 ? ' · ' + p.bloecke + ' Blöcke' : '';
    if (p.form === 'termin' && p.teilung === 'getrennt' && p.termine && p.termine.length) {
      return 'getrennt: ' + p.termine.map(t => t.gruppe + ' ' + tagKurz(t.datum) + ' ' + t.beginn).join(', ') + umfang;
    }
    if (p.form === 'termin') return tagKurz(p.datum) + ' · ' + p.beginn + umfang;
    return 'Fenster ' + tagKurz(p.fenster_von) + ' – ' + tagKurz(p.fenster_bis) + ' (Frist)';
  }

  function pruefungKarte(p) {
    const st = p.statistik;
    const [standText, standFarbe] = STAND[p.stand] || [p.stand, ''];
    return el('a', { class: 'karte klassenkarte', href: '#pruefung-' + p.id },
      el('div', { class: 'zeile' }, L.symbol('pruefung'), el('h3', { text: p.titel }), el('span', { class: 'rechts' }, el('span', { class: 'chip ' + standFarbe, text: standText }))),
      el('div', { class: 'leise klein', text: p.artname + ' · ' + ERFASSUNG[p.erfassung] + ' · ' + wannText(p) }),
      p.hinweise && p.hinweise.length ? el('div', { class: 'chip gelb klein', title: p.hinweise.join('\n'), text: 'Termin prüfen: ' + p.hinweise[0] }) : null,
      el('div', { class: 'zeile klein' },
        el('span', { text: st.bewertet + ' von ' + st.schueler + ' bewertet' }),
        st.schnitt !== null ? el('span', { class: 'chip blau', text: 'Ø ' + fmt(st.schnitt, 2) }) : null,
        st.fehlt ? el('span', { class: 'chip', text: st.fehlt + ' gefehlt' }) : null));
  }

  // --- Pruefung anlegen / bearbeiten ---

  // vorgabe: { klasse_id, gruppe_id, schuljahr_id, datum, beginn } beim Anlegen
  async function pruefungDialog(p, R, vorgabe, danach) {
    await grunddaten();
    R = R || await L.api('GET', '/api/pruefungen');
    const kid = p ? p.klasse_id : vorgabe.klasse_id;
    const titel = el('input', { maxlength: 120, value: p ? p.titel : '', placeholder: 'z. B. Klassenarbeit LF 7' });
    const art = el('select', {}, ARTEN.map(([w, t]) => el('option', { value: w, text: t, selected: p && p.art === w ? true : null })));
    const lf = el('select', {}, el('option', { value: '', text: '– ohne –' }), lernfelderDerKlasse(kid).map(l =>
      el('option', { value: l.id, text: l.nummer + ' ' + l.name, selected: p && p.lernfeld_id === l.id ? true : null })));
    // Zeitform
    let form = p ? p.form : 'termin';
    const datum = el('input', { type: 'date', value: p && p.datum ? p.datum : (vorgabe && vorgabe.datum) || '' });
    const block = el('select', {}, bloeckeDerKlasse(kid).map(b => el('option', { value: b.beginn, text: b.bezeichnung + ' · ' + b.beginn + '–' + b.ende,
      selected: (p ? p.beginn : vorgabe && vorgabe.beginn) === b.beginn ? true : null })));
    const bloecke = el('input', { type: 'number', min: 1, max: 20, value: p ? p.bloecke : 1, style: 'width:90px' });
    const von = el('input', { type: 'date', value: p && p.fenster_von ? p.fenster_von : '' });
    const bis = el('input', { type: 'date', value: p && p.fenster_bis ? p.fenster_bis : '' });
    // Gruppen der Klasse: zusammen schreiben (ein Termin) oder getrennt (Termin je Gruppe)
    const U = await L.api('GET', '/api/pruefungen/unterricht?klasse=' + kid);
    const gruppen = U.gruppen;
    let teilung = p ? p.teilung : (vorgabe && vorgabe.gruppe_id && gruppen.length > 1 ? 'getrennt' : 'zusammen');
    const startTag = (p && p.datum) || (vorgabe && vorgabe.datum) || '';
    const gruppenTermine = gruppen.map(g => {
      const alt = p && p.termine ? p.termine.find(t => t.gruppe_id === g.id) : null;
      const gDatum = el('input', { type: 'date', value: alt ? alt.datum : startTag, 'aria-label': 'Tag für ' + g.name });
      const gBlock = el('select', { 'aria-label': 'Block für ' + g.name }, bloeckeDerKlasse(kid).map(b => el('option', { value: b.beginn, text: b.bezeichnung + ' · ' + b.beginn,
        selected: (alt ? alt.beginn : vorgabe && vorgabe.gruppe_id === g.id ? vorgabe.beginn : null) === b.beginn ? true : null })));
      return { g, gDatum, gBlock, gesetzt: !!alt || !!(vorgabe && vorgabe.gruppe_id === g.id) };
    });
    // Block der Gruppe an ihrem Tag aus dem Stundenplan vorschlagen
    async function blockVorschlagen(t, immer) {
      if (!t.gDatum.value) return;
      try {
        const x = await L.api('GET', '/api/pruefungen/unterricht?klasse=' + kid + '&datum=' + t.gDatum.value);
        const b = x.bloecke.find(y => y.gruppe_id === t.g.id);
        if (b && (immer || !t.gesetzt)) t.gBlock.value = b.beginn;
      } catch (e) { /* Hinweis kommt aus pruefen() */ }
      pruefen();
    }
    gruppenTermine.forEach(t => {
      t.gDatum.addEventListener('change', () => { t.gesetzt = false; blockVorschlagen(t, true); });
      t.gBlock.addEventListener('change', () => { t.gesetzt = true; pruefen(); });
    });
    const teilZusammen = el('div', { class: 'felder zwei' }, L.feld('Tag', datum), L.feld('Erster Block', block));
    const teilGetrennt = el('div', { class: 'stapel', style: 'gap:6px' }, gruppenTermine.map(t =>
      el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, el('span', { class: 'chip gr', style: 'min-width:70px', text: t.g.name }), t.gDatum, t.gBlock)),
      el('p', { class: 'leise klein', text: 'Gruppen am selben Tag schreiben in ihren zusammengehörenden Stunden; die Planung belegt den Tag des ersten Termins.' }));
    const hinweisOrt = el('div', { class: 'banner warnung klein', hidden: true });
    let pruefLauf = 0;
    async function pruefen() {
      const lauf = ++pruefLauf;
      const termine = form !== 'termin' ? [] : teilung === 'getrennt'
        ? gruppenTermine.map(t => ({ gruppe_id: t.g.id, datum: t.gDatum.value, beginn: t.gBlock.value }))
        : [{ gruppe_id: null, datum: datum.value, beginn: block.value }];
      let h = [];
      try {
        if (termine.some(t => t.datum)) h = (await L.api('GET', '/api/pruefungen/unterricht?klasse=' + kid + '&termine=' + encodeURIComponent(JSON.stringify(termine)))).hinweise;
      } catch (e) { h = []; }
      if (lauf !== pruefLauf) return;
      L.setzen(hinweisOrt, h.map(x => el('div', { text: x })));
      hinweisOrt.hidden = !h.length;
    }
    datum.addEventListener('change', pruefen);
    block.addEventListener('change', pruefen);
    const zeigeTeilung = w => { teilung = w; teilZusammen.hidden = w !== 'zusammen'; teilGetrennt.hidden = w !== 'getrennt';
      if (w === 'getrennt') gruppenTermine.forEach(t => { if (!t.gDatum.value && datum.value) t.gDatum.value = datum.value; if (!t.gesetzt) blockVorschlagen(t); });
      pruefen(); };
    const segTeilung = gruppen.length > 1 ? segment([['zusammen', 'Klasse zusammen'], ['getrennt', 'Getrennt nach Gruppen']], teilung, zeigeTeilung) : null;
    if (gruppen.length < 2) teilung = 'zusammen';
    const teilTermin = el('div', { class: 'stapel', style: 'gap:8px' }, segTeilung, teilZusammen, teilGetrennt,
      el('div', { class: 'felder zwei' }, L.feld('Umfang in Blöcken', bloecke, 'belegt die Blöcke in der Planung')), hinweisOrt);
    teilZusammen.hidden = teilung !== 'zusammen';
    teilGetrennt.hidden = teilung !== 'getrennt';
    const teilFenster = el('div', { class: 'felder zwei' }, L.feld('Fenster ab', von), L.feld('Frist (spätestens)', bis, 'belegt keine Blöcke'));
    const segForm = segment([['termin', 'Fester Termin'], ['fenster', 'Fenster mit Frist']], form, w => { form = w; teilTermin.hidden = w !== 'termin'; teilFenster.hidden = w !== 'fenster'; pruefen(); });
    teilTermin.hidden = form !== 'termin';
    teilFenster.hidden = form !== 'fenster';
    // Erfassung
    let erfassung = p ? p.erfassung : 'aufgaben';
    const aufgabenOrt = el('div', { class: 'stapel', style: 'gap:6px' });
    const aufgaben = [];
    const aufgabeNeu = a => {
      const name = el('input', { maxlength: 120, value: a ? a.name : 'Aufgabe ' + (aufgaben.length + 1), 'aria-label': 'Aufgabe' });
      const max = el('input', { inputmode: 'decimal', value: a ? fmt(a.max) : '', placeholder: 'Punkte', style: 'width:90px', 'aria-label': 'Höchstpunkte' });
      const eintrag = { key: a ? a.key : null, name, max };
      const zeile = el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, name, max, el('span', { class: 'leise klein', text: 'P' }),
        el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Aufgabe entfernen', onclick: () => { aufgaben.splice(aufgaben.indexOf(eintrag), 1); zeile.remove(); summe(); } }, L.symbol('zu')));
      max.addEventListener('input', summe);
      aufgaben.push(eintrag);
      aufgabenOrt.appendChild(zeile);
    };
    const summeText = el('span', { class: 'leise klein' });
    function summe() { summeText.textContent = 'zusammen ' + fmt(aufgaben.reduce((n, a) => n + (parseFloat(a.max.value.replace(',', '.')) || 0), 0)) + ' Punkte'; }
    const alteAufgaben = p && p.erfassung === 'aufgaben' ? p.struktur.bereiche[0].kriterien : [];
    (alteAufgaben.length ? alteAufgaben : [null, null, null]).forEach(aufgabeNeu);
    summe();
    const maxPunkte = el('input', { inputmode: 'decimal', value: p && p.max_punkte ? fmt(p.max_punkte) : '', style: 'width:120px' });
    const vorlage = el('select', {}, el('option', { value: '', text: R.vorlagen.length ? '– Vorlage wählen –' : 'noch keine Vorlage (Reiter „Vorlagen“)' }),
      R.vorlagen.map(v => el('option', { value: v.id, text: v.name })));
    const teilAufgaben = el('div', { class: 'stapel', style: 'gap:8px' }, aufgabenOrt,
      el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'klein', onclick: () => { aufgabeNeu(null); summe(); } }, L.symbol('plus'), 'Aufgabe'), summeText));
    const teilGesamt = L.feld('Höchstpunkte', maxPunkte);
    const teilBogen = el('div', { class: 'stapel', style: 'gap:6px' },
      p && p.erfassung === 'bogen' ? el('p', { class: 'leise klein', text: 'Bogen dieser Prüfung: ' + p.struktur.bereiche.map(b => b.name).join(', ') + '. Eine andere Vorlage ersetzt ihn.' }) : null,
      L.feld(p && p.erfassung === 'bogen' ? 'Andere Vorlage übernehmen' : 'Vorlage', vorlage));
    const zeigeErfassung = w => { erfassung = w; teilAufgaben.hidden = w !== 'aufgaben'; teilGesamt.hidden = w !== 'gesamt'; teilBogen.hidden = w !== 'bogen'; };
    const segErfassung = segment(Object.entries(ERFASSUNG), erfassung, zeigeErfassung);
    zeigeErfassung(erfassung);
    // Notenschluessel und Stand
    const schl = el('select', {}, el('option', { value: '', text: 'automatisch (Klasse → dein Standard → Konferenz)' }),
      R.schluessel.map(s => el('option', { value: s.id, text: s.name + ' · ' + s.systemname + (s.art === 'eigen' ? ' · eigener' : ''),
        selected: p && p.notenschluessel_id === s.id ? true : null })));
    const stand = el('select', {}, ['geplant', 'angekuendigt', 'durchgefuehrt'].map(w => el('option', { value: w, text: STAND[w][0], selected: p && p.stand === w ? true : null })));
    if (teilung === 'getrennt' && !p) gruppenTermine.forEach(t => { if (!t.gesetzt) blockVorschlagen(t); });
    pruefen();
    const r = await L.dialog({
      titel: p ? 'Prüfung bearbeiten' : 'Neue Prüfung', breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('div', { class: 'felder zwei' }, L.feld('Titel', titel), L.feld('Art', art)),
        el('div', { class: 'felder zwei' }, L.feld('Lernfeld', lf), p && p.stand !== 'ausgewertet' ? L.feld('Stand', stand) : el('span')),
        el('div', { class: 'stapel', style: 'gap:8px' }, el('span', { class: 'etikett', text: 'Zeit' }), segForm, teilTermin, teilFenster),
        el('div', { class: 'stapel', style: 'gap:8px' }, el('span', { class: 'etikett', text: 'Erfassung' }), segErfassung, teilAufgaben, teilGesamt, teilBogen),
        L.feld('Notenschlüssel', schl, 'Ein eigener Schlüssel erscheint in der Prüfung als abweichender Schlüssel.'),
        p ? el('div', {}, L.nebenknopf('Prüfung löschen …', () => loeschen(p))) : null),
      speichern: () => L.api('POST', p ? '/api/pruefung/' + p.id : '/api/pruefung', Object.assign(p ? {} : { klasse_id: vorgabe.klasse_id, gruppe_id: vorgabe.gruppe_id, schuljahr_id: vorgabe.schuljahr_id }, {
        titel: titel.value, art: art.value, lernfeld_id: lf.value || null, form, datum: datum.value, beginn: block.value, bloecke: Number(bloecke.value),
        teilung, termine: teilung === 'getrennt' ? gruppenTermine.map(t => ({ gruppe_id: t.g.id, datum: t.gDatum.value, beginn: t.gBlock.value })) : undefined,
        fenster_von: von.value, fenster_bis: bis.value, erfassung, notenschluessel_id: schl.value || null, stand: stand.value,
        aufgaben: erfassung === 'aufgaben' ? aufgaben.map(a => ({ key: a.key, name: a.name.value, max: a.max.value })) : undefined,
        max_punkte: erfassung === 'gesamt' ? maxPunkte.value : undefined,
        vorlage_id: erfassung === 'bogen' && vorlage.value ? Number(vorlage.value) : undefined })),
    });
    if (!r) return;
    if (danach) danach(r.id);
    else location.hash = '#pruefung-' + r.id;
  }

  function segment(werte, aktiv, aendern) {
    const seg = el('div', { class: 'segment', role: 'group' });
    werte.forEach(([w, t]) => seg.appendChild(el('button', { type: 'button', class: w === aktiv ? 'an' : null, 'data-w': w,
      onclick: () => { [...seg.children].forEach(b => b.classList.toggle('an', b.dataset.w === w)); aendern(w); } }, t)));
    return seg;
  }

  async function loeschen(p) {
    const r = await L.dialog({
      titel: 'Prüfung löschen?', knopf: 'Löschen', gefaehrlich: true,
      inhalt: el('p', { text: '„' + p.titel + '“ mit allen Bewertungen löschen? Ein fester Termin verschwindet auch aus der Planung.' }),
      speichern: () => L.api('POST', '/api/pruefung/' + p.id + '/loeschen', {}),
    });
    if (r) location.hash = '#pruefungen';
  }

  // --- Eine Pruefung: Bewerten und Auswertung ---

  let E = null;          // Ergebnis der Pruefung
  let reiter = 'bewerten';

  async function detailZeigen(pid) {
    E = await L.api('GET', '/api/pruefung/' + pid);
    detailZeichnen();
  }

  function schluesselText() {
    if (!E.schluessel) return el('span', { class: 'chip rot', text: 'Kein Notenschlüssel: der Admin trägt den Konferenzschlüssel ein' });
    return el('span', { class: 'chip' + (E.schluessel.art === 'eigen' ? ' gelb' : ''), title: E.herkunft },
      L.symbol('schluessel'), E.schluessel.name + ' · ' + E.schluessel.systemname + (E.schluessel.art === 'eigen' ? ' · abweichender Schlüssel' : ''));
  }

  function detailZeichnen() {
    const p = E.pruefung;
    const st = E.statistik;
    const fertig = p.stand === 'ausgewertet';
    const [standText, standFarbe] = STAND[p.stand] || [p.stand, ''];
    const rumpf = el('div', { class: 'stapel' });
    L.setzen(ort,
      el('div', { class: 'zeile' }, el('a', { class: 'knopf', href: '#pruefungen' }, L.symbol('links'), 'Alle Prüfungen'),
        el('h2', { text: p.titel }), el('span', { class: 'chip ' + standFarbe, text: standText }),
        el('span', { class: 'rechts' },
          !fertig ? el('button', { type: 'button', onclick: async () => pruefungDialog(p, null, null, () => detailZeigen(p.id)) }, L.symbol('stift'), 'Bearbeiten') : null,
          fertig ? el('button', { type: 'button', onclick: oeffnen }, L.symbol('undo'), 'Wieder öffnen')
            : el('button', { type: 'button', class: 'haupt', onclick: abschliessen }, L.symbol('ok'), 'Abschließen'))),
      el('div', { class: 'zeile leise klein' }, el('span', { text: p.artname + ' · ' + ERFASSUNG[p.erfassung] + ' · ' + wannText(p) }), schluesselText(),
        el('span', { text: E.herkunft })),
      el('div', { class: 'zeile' },
        segment([['bewerten', 'Bewerten'], ['auswertung', 'Auswertung']], reiter, w => { reiter = w; detailZeichnen(); }),
        kopfStatistik(st)),
      fertig ? el('div', { class: 'banner', text: 'Abgeschlossen: Der Notenschlüssel ist festgehalten, Bewertungen sind gesperrt. „Wieder öffnen“ hebt das auf.' }) : null,
      p.hinweise && p.hinweise.length ? el('div', { class: 'banner warnung' }, p.hinweise.map(h => el('div', { text: h }))) : null,
      rumpf);
    zeichneRumpf(rumpf);
  }

  function kopfStatistik(st) {
    return el('span', { class: 'zeile pr-statistik' },
      el('span', { class: 'leise klein', text: st.bewertet + ' von ' + st.schueler + ' bewertet' + (st.fehlt ? ' · ' + st.fehlt + ' gefehlt' : '') }),
      st.schnitt !== null ? el('span', { class: 'chip blau', text: 'Ø ' + fmt(st.schnitt, 2) + ' · ' + fmt(st.prozent) + ' %' }) : null);
  }

  function zeichneRumpf(rumpf) {
    if (!E.schueler.length) {
      return L.setzen(rumpf, el('div', { class: 'leer' }, 'Für diese Klasse gibt es noch keine Schülerliste. ', el('a', { href: '#pruefungen-schueler', text: 'Schülerliste anlegen' })));
    }
    L.setzen(rumpf, reiter === 'auswertung' ? auswertung() : bewertenTabelle());
  }

  async function speichern(sid, daten) {
    try {
      E = await L.api('POST', '/api/pruefung/' + E.pruefung.id + '/bewertung/' + sid, daten);
      return true;
    } catch (e) { L.meldung(e.message, true); return false; }
  }

  function noteZelle(z) {
    if (z.fehlt) return el('td', { class: 'leise', text: 'fehlt' });
    if (!z.note) return el('td', { class: 'leise', text: '–' });
    return el('td', {}, el('button', { type: 'button', class: 'note-knopf' + (z.fehlend.length ? ' unvollstaendig' : ''),
      title: 'Rechenweg anzeigen', onclick: () => rechenweg(z) }, z.note.text));
  }

  function rechenweg(z) {
    L.dialog({
      titel: 'Rechenweg · ' + z.name, knopf: 'Schließen', abbrechen: null, speichern: () => true,
      inhalt: el('div', { class: 'stapel', style: 'gap:6px' },
        z.rechenweg.map(r => el('div', { class: 'mono klein rechenweg-zeile', text: r })),
        z.fehlend.length ? el('div', { class: 'banner warnung', text: 'Nicht bewertet und nicht mitgerechnet: ' + z.fehlend.join(', ') }) : null,
        z.notiz ? el('p', { class: 'klein' }, el('b', { text: 'Notiz: ' }), z.notiz) : null),
    });
  }

  // Tabelle: Aufgaben bzw. Gesamtpunkte direkt eintippen; Feedbackbogen ueber ein Overlay je Schueler
  function bewertenTabelle() {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    const kriterien = p.erfassung === 'aufgaben' ? p.struktur.bereiche[0].kriterien : [];
    const kopf = el('tr', {}, el('th', { text: 'Schüler' }),
      p.erfassung === 'aufgaben' ? kriterien.map(k => el('th', { class: 'zahl', title: k.name }, k.name, el('br'), el('span', { class: 'leise', text: 'max ' + fmt(k.max) }))) : null,
      p.erfassung === 'gesamt' ? el('th', { class: 'zahl' }, 'Punkte', el('br'), el('span', { class: 'leise', text: 'max ' + fmt(p.max_punkte) })) : null,
      p.erfassung === 'bogen' ? p.struktur.bereiche.map(b => el('th', { class: 'zahl', text: b.name })) : null,
      el('th', { class: 'zahl', text: '%' }), el('th', { text: 'Note' }), el('th', { text: 'fehlt' }));
    const eingaben = [];   // fuer Enter = naechste Zeile
    const zeilen = E.schueler.map((z, zi) => {
      const tr = el('tr', { class: z.aktiv ? null : 'aus' });
      const ergebnisZellen = () => [el('td', { class: 'zahl mono', text: z.prozent !== null && !z.fehlt ? fmt(z.prozent) : '–' }), noteZelle(z)];
      const feld = (key, wert, max) => {
        const i = el('input', { class: 'punkte', inputmode: 'decimal', value: wert === undefined || wert === null ? '' : fmt(wert, 2), disabled: fertig || z.fehlt ? true : null,
          'aria-label': z.name + ' ' + key, title: 'max ' + fmt(max) });
        i.addEventListener('change', async () => {
          const ok = await speichern(z.id, { werte: { [key]: i.value.replace(',', '.') } });
          if (!ok) { i.classList.add('fehler'); return; }
          i.classList.remove('fehler');
          const neu = E.schueler.find(x => x.id === z.id);
          const zellen = tr.querySelectorAll('td');
          zellen[zellen.length - 3].replaceWith(el('td', { class: 'zahl mono', text: neu.prozent !== null ? fmt(neu.prozent) : '–' }));
          tr.querySelectorAll('td')[tr.querySelectorAll('td').length - 2].replaceWith(noteZelle(neu));
          Object.assign(z, neu);
          kopfZahlen();
        });
        i.addEventListener('keydown', ev => {
          if (ev.key === 'Enter') { ev.preventDefault(); const naechste = eingaben[zi + 1]; if (naechste) naechste[[...tr.querySelectorAll('input.punkte')].indexOf(i)].focus(); }
        });
        return i;
      };
      const meine = [];
      tr.appendChild(el('td', {}, el('b', { text: z.name }), z.gruppe ? el('span', { class: 'chip klein gr', text: z.gruppe }) : null,
        z.notiz ? el('span', { class: 'leise klein', title: z.notiz, text: ' ✎' }) : null));
      if (p.erfassung === 'aufgaben') kriterien.forEach(k => { const i = feld(k.key, z.werte[k.key], k.max); meine.push(i); tr.appendChild(el('td', { class: 'zahl' }, i)); });
      if (p.erfassung === 'gesamt') { const i = feld('gesamt', z.werte.gesamt, p.max_punkte); meine.push(i); tr.appendChild(el('td', { class: 'zahl' }, i)); }
      if (p.erfassung === 'bogen') {
        p.struktur.bereiche.forEach((b, bi) => tr.appendChild(el('td', { class: 'zahl mono', text: z.bereiche[bi] && z.bereiche[bi].prozent !== null ? fmt(z.bereiche[bi].prozent) + ' %' : '–' })));
        tr.firstChild.appendChild(el('button', { type: 'button', class: 'klein bogen-knopf', disabled: z.fehlt ? true : null,
          onclick: () => bogen(z.id) }, L.symbol('stift'), fertig ? 'ansehen' : 'Bogen'));
      }
      eingaben.push(meine);
      ergebnisZellen().forEach(c => tr.appendChild(c));
      const fehlt = el('input', { type: 'checkbox', checked: z.fehlt ? true : null, disabled: fertig ? true : null, 'aria-label': z.name + ' fehlt' });
      fehlt.addEventListener('change', async () => { if (await speichern(z.id, { fehlt: fehlt.checked })) detailZeichnen(); });
      tr.appendChild(el('td', {}, fehlt));
      return tr;
    });
    const kopfZahlen = () => { const alt = ort.querySelector('.pr-statistik'); if (alt) alt.replaceWith(kopfStatistik(E.statistik)); };
    return el('div', { class: 'stapel', style: 'gap:8px' },
      el('div', { class: 'r-scroll' }, el('table', { class: 'liste bewerten' }, el('thead', {}, kopf), el('tbody', {}, zeilen))),
      el('p', { class: 'leise klein', text: p.erfassung === 'bogen'
        ? '„Bogen“ öffnet den Feedbackbogen des Schülers; jede Eingabe wird sofort gespeichert. Tipp auf die Note zeigt den Rechenweg.'
        : 'Eintippen und mit Tab oder Enter weiter; jede Eingabe wird sofort gespeichert. Leeres Feld = nicht bewertet. Tipp auf die Note zeigt den Rechenweg; eine gelb umrandete Note hat unbewertete Aufgaben.' }));
  }

  // Feedbackbogen eines Schuelers im Overlay
  async function bogen(sid) {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    let z = E.schueler.find(x => x.id === sid);
    const ergebnisOrt = el('div', { class: 'bogen-ergebnis' });
    const zeigeErgebnis = () => {
      z = E.schueler.find(x => x.id === sid);
      L.setzen(ergebnisOrt, el('div', { class: 'zeile' }, el('b', { text: 'Ergebnis' }),
        el('span', { class: 'chip blau', text: z.note ? z.note.text + ' · ' + fmt(z.prozent) + ' %' : 'noch keine Note' }),
        z.fehlend.length ? el('span', { class: 'leise klein', text: 'offen: ' + z.fehlend.join(', ') }) : null),
      z.rechenweg.map(r => el('div', { class: 'mono klein rechenweg-zeile', text: r })));
    };
    const setze = async (key, wert) => { if (await speichern(sid, { werte: { [key]: wert } })) zeigeErgebnis(); };
    const bereiche = p.struktur.bereiche.map(b => el('section', { class: 'ov-ab' },
      el('div', { class: 'ab-kopf' }, el('span', { text: b.name }), el('span', { class: 'leise klein', text: 'Gewicht ' + fmt(b.gewicht) })),
      el('div', { class: 'ab-inhalt' }, b.kriterien.map(k => {
        const wert = z.werte[k.key];
        let eingabe;
        if (k.typ === 'stufen') {
          eingabe = el('div', { class: 'stufen-wahl', role: 'group', 'aria-label': k.name }, k.stufen.map((s, i) => {
            const knopf = el('button', { type: 'button', class: wert === i ? 'an' : null, disabled: fertig ? true : null, title: s.text || null,
              onclick: () => {
                const neu = knopf.classList.contains('an') ? null : i;   // erneuter Tipp nimmt zurueck
                [...knopf.parentNode.children].forEach(x => x.classList.remove('an'));
                if (neu !== null) knopf.classList.add('an');
                setze(k.key, neu);
              } }, el('b', { text: s.name }), el('span', { class: 'leise', text: fmt(s.punkte) + ' P' }));
            return knopf;
          }));
        } else if (k.typ === 'punkte') {
          eingabe = el('div', { class: 'zeile' }, el('input', { inputmode: 'decimal', class: 'punkte', value: wert === undefined ? '' : fmt(wert, 2), disabled: fertig ? true : null,
            onchange: ev => setze(k.key, ev.target.value.replace(',', '.')) }), el('span', { class: 'leise', text: 'von ' + fmt(k.max) + ' P' }));
        } else if (k.typ === 'haken') {
          eingabe = el('label', { class: 'haken' }, el('input', { type: 'checkbox', checked: wert ? true : null, disabled: fertig ? true : null,
            onchange: ev => setze(k.key, ev.target.checked ? true : null) }), 'erledigt (nur Information)');
        } else {
          const t = el('textarea', { rows: 2, disabled: fertig ? true : null, onchange: ev => setze(k.key, ev.target.value) });
          t.value = wert || '';
          eingabe = t;
        }
        return el('div', { class: 'kriterium' }, el('div', { class: 'zeile' }, el('b', { text: k.name }),
          k.gewicht ? el('span', { class: 'chip klein', text: '×' + fmt(k.gewicht) }) : null), eingabe);
      }))));
    const notiz = el('textarea', { rows: 2, disabled: fertig ? true : null, placeholder: 'Gesamteindruck, Begründung …', onchange: ev => speichern(sid, { notiz: ev.target.value }) });
    notiz.value = z.notiz || '';
    zeigeErgebnis();
    await L.dialog({
      titel: 'Feedbackbogen · ' + z.name, knopf: 'Fertig', abbrechen: null, breit: true, fokus: false, speichern: () => true,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, bereiche, L.feld('Notiz', notiz), ergebnisOrt),
    });
    detailZeichnen();
  }

  // Auswertung: Notenspiegel, Schnitt, Aufgaben bzw. Kriterien
  function auswertung() {
    const st = E.statistik;
    const stufen = Object.keys(st.spiegel);
    const hoechst = Math.max(1, ...Object.values(st.spiegel));
    const breite = 36, hoehe = 120;
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + (stufen.length * breite + 10) + ' ' + (hoehe + 34));
    svg.setAttribute('class', 'spiegel');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Notenspiegel: ' + stufen.map(s => s + ': ' + st.spiegel[s]).join(', '));
    stufen.forEach((s, i) => {
      const n = st.spiegel[s];
      const h = n ? Math.max(4, hoehe * n / hoechst) : 0;
      const r = document.createElementNS(ns, 'rect');
      Object.entries({ x: 5 + i * breite + 4, y: hoehe - h + 14, width: breite - 8, height: h, rx: 3, class: 'balken' }).forEach(([a, w]) => r.setAttribute(a, w));
      svg.appendChild(r);
      const t1 = document.createElementNS(ns, 'text');
      Object.entries({ x: 5 + i * breite + breite / 2, y: hoehe + 30, 'text-anchor': 'middle', class: 'achse' }).forEach(([a, w]) => t1.setAttribute(a, w));
      t1.textContent = E.schluessel && E.schluessel.system === 'punkte' ? s : s;
      svg.appendChild(t1);
      if (n) {
        const t2 = document.createElementNS(ns, 'text');
        Object.entries({ x: 5 + i * breite + breite / 2, y: hoehe - h + 10, 'text-anchor': 'middle', class: 'wert' }).forEach(([a, w]) => t2.setAttribute(a, w));
        t2.textContent = n;
        svg.appendChild(t2);
      }
    });
    return el('div', { class: 'zwei-spalten' },
      el('div', { class: 'karte stapel' }, el('h3', { text: 'Notenspiegel' }),
        stufen.length ? svg : el('p', { class: 'leise', text: 'Kein Notenschlüssel.' }),
        el('div', { class: 'zeile klein' },
          el('span', { text: 'Schnitt ' + fmt(st.schnitt, 2) }), el('span', { class: 'leise', text: '· Ø ' + fmt(st.prozent) + ' %' }),
          el('span', { class: 'leise', text: '· ' + st.bewertet + ' bewertet' + (st.fehlt ? ', ' + st.fehlt + ' gefehlt' : '') + (st.offen ? ', ' + st.offen + ' offen' : '') }))),
      st.aufgaben.length ? el('div', { class: 'karte stapel' }, el('h3', { text: E.pruefung.erfassung === 'aufgaben' ? 'Aufgaben' : 'Kriterien' }),
        el('table', { class: 'liste' }, el('tbody', {}, st.aufgaben.map(a => el('tr', {},
          el('td', { text: a.name }),
          el('td', { style: 'width:45%' }, el('div', { class: 'anteil' }, el('span', { style: 'width:' + Math.round(a.prozent || 0) + '%' }))),
          el('td', { class: 'mono zahl', style: a.prozent !== null && a.prozent < 50 ? 'color:var(--rot);font-weight:700' : null, text: a.prozent !== null ? fmt(a.prozent) + ' %' : '–' })))))) : null);
  }

  async function abschliessen() {
    const st = E.statistik;
    const r = await L.dialog({
      titel: 'Prüfung abschließen?', knopf: 'Abschließen',
      inhalt: el('div', { class: 'stapel', style: 'gap:8px' },
        el('p', { text: 'Der Notenschlüssel wird festgehalten, Bewertungen lassen sich danach nur nach „Wieder öffnen“ ändern.' }),
        st.offen ? el('div', { class: 'banner warnung', text: st.offen + ' Schüler ohne Bewertung.' }) : null,
        st.unvollstaendig ? el('div', { class: 'banner warnung', text: st.unvollstaendig + ' Bewertungen mit unbewerteten Aufgaben bzw. Kriterien (nicht mitgerechnet).' }) : null),
      speichern: () => L.api('POST', '/api/pruefung/' + E.pruefung.id + '/abschliessen', {}),
    });
    if (r) { E = r; L.meldung('Abgeschlossen.'); detailZeichnen(); }
  }

  async function oeffnen() {
    try { E = await L.api('POST', '/api/pruefung/' + E.pruefung.id + '/oeffnen', {}); detailZeichnen(); } catch (e) { L.meldung(e.message, true); }
  }

  // --- Schuelerlisten ---

  let listeKlasse = null;

  async function schuelerZeigen() {
    const P = await strangLaden();
    const meine = [...new Map(P.straenge.map(s => [s.klasse_id, s.klasse])).entries()];
    const alle = G.klassen.filter(k => k.aktiv);
    if (!listeKlasse) listeKlasse = wahl.klasse || (meine[0] && meine[0][0]) || (alle[0] && alle[0].id);
    if (!listeKlasse) return L.setzen(ort, el('div', { class: 'leer', text: 'Es gibt noch keine Klassen.' }));
    const [S, SP] = await Promise.all([L.api('GET', '/api/schueler?klasse=' + listeKlasse), L.api('GET', '/api/stundenplan')]);
    const gruppen = SP.gruppen.filter(g => g.klasse_id === listeKlasse);
    const auswahl = el('select', { 'aria-label': 'Klasse', style: 'width:auto', onchange: () => { listeKlasse = Number(auswahl.value); schuelerZeigen(); } },
      el('optgroup', { label: 'Meine Klassen' }, meine.map(([id, name]) => el('option', { value: id, text: name, selected: id === listeKlasse ? true : null }))),
      el('optgroup', { label: 'Alle Klassen' }, alle.filter(k => !meine.some(([id]) => id === k.id)).map(k => el('option', { value: k.id, text: k.name, selected: k.id === listeKlasse ? true : null }))));
    const datei = el('input', { type: 'file', accept: '.csv,text/csv', hidden: true, onchange: async () => {
      const f = datei.files[0];
      if (!f) return;
      try {
        const r = await L.api('POST', '/api/schueler/moodle', { klasse_id: listeKlasse, text: await f.text() });
        L.meldung(r.neu.length + ' neu, ' + r.vorhanden.length + ' schon vorhanden' + (r.leer ? ', ' + r.leer + ' Zeilen ohne Namen' : '') + '.');
        schuelerZeigen();
      } catch (e) { L.meldung(e.message, true); }
      datei.value = '';
    } });
    L.setzen(ort,
      el('div', { class: 'zeile' }, auswahl, el('span', { class: 'leise klein', text: S.schueler.filter(s => s.aktiv).length + ' Schüler · nur für dich sichtbar' }),
        el('span', { class: 'rechts' }, datei,
          el('button', { type: 'button', onclick: () => datei.click() }, L.symbol('hoch'), 'Moodle-CSV einlesen'),
          el('button', { type: 'button', class: 'haupt', onclick: () => schuelerDialog(null, gruppen) }, L.symbol('plus'), 'Schüler'))),
      el('p', { class: 'leise klein', text: 'Moodle: Kurs → Teilnehmer/innen → alle auswählen → „Download als CSV“. Beim Einlesen kommen nur neue Schüler dazu; vorhandene Namen werden nie geändert.' }),
      S.schueler.length ? el('div', { class: 'karte rollbar' }, el('table', { class: 'liste' },
        el('thead', {}, el('tr', {}, ['Name', 'E-Mail', gruppen.length ? 'Gruppe' : '', ''].map(t => el('th', { text: t })))),
        el('tbody', {}, S.schueler.map(s => el('tr', { class: 'klickbar' + (s.aktiv ? '' : ' aus'), tabindex: '0', onclick: () => schuelerDialog(s, gruppen),
          onkeydown: ev => { if (ev.key === 'Enter') schuelerDialog(s, gruppen); } },
          el('td', {}, el('b', { text: s.name })), el('td', { class: 'leise klein', text: s.email || '' }),
          el('td', {}, s.gruppe ? el('span', { class: 'chip gr', text: s.gruppe }) : null),
          el('td', {}, s.aktiv ? null : el('span', { class: 'chip', text: 'nicht mehr in der Klasse' }))))))) :
        el('div', { class: 'leer', text: 'Noch keine Schüler. Lies die Teilnehmerliste aus Moodle ein oder lege Schüler von Hand an.' }));
  }

  async function schuelerDialog(s, gruppen) {
    const nachname = el('input', { maxlength: 80, value: s ? s.nachname : '' });
    const vorname = el('input', { maxlength: 80, value: s ? s.vorname : '' });
    const email = el('input', { maxlength: 120, value: s ? s.email : '', type: 'email' });
    const gruppe = el('select', {}, el('option', { value: '', text: '– keine –' }), gruppen.map(g => el('option', { value: g.id, text: g.name, selected: s && s.gruppe_id === g.id ? true : null })));
    const aktiv = el('input', { type: 'checkbox', checked: !s || s.aktiv ? true : null });
    const r = await L.dialog({
      titel: s ? s.name : 'Neuer Schüler',
      inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Nachname', nachname), L.feld('Vorname', vorname)),
        L.feld('E-Mail', email, 'freiwillig, hilft beim Abgleich mit Moodle'), gruppen.length ? L.feld('Gruppe', gruppe) : null,
        s ? el('label', { class: 'haken' }, aktiv, 'in der Klasse (sonst nur noch in alten Prüfungen sichtbar)') : null,
        s ? el('div', {}, L.nebenknopf('Schüler löschen …', async () => {
          const ok = await L.dialog({ titel: s.name + ' löschen?', knopf: 'Löschen', gefaehrlich: true,
            inhalt: el('p', { text: 'Geht nur ohne Bewertungen; sonst bitte „nicht mehr in der Klasse“.' }),
            speichern: () => L.api('POST', '/api/schueler/' + s.id + '/loeschen', {}) });
          if (ok) schuelerZeigen();
        })) : null),
      speichern: () => L.api('POST', s ? '/api/schueler/' + s.id : '/api/schueler', { klasse_id: listeKlasse, nachname: nachname.value, vorname: vorname.value,
        email: email.value, gruppe_id: gruppe.value || null, aktiv: aktiv.checked }),
    });
    if (r) schuelerZeigen();
  }

  // --- Vorlagen (Feedbackbogen) ---

  async function vorlagenZeigen() {
    const R = await L.api('GET', '/api/pruefungen');
    L.setzen(ort,
      el('div', { class: 'zeile' }, el('p', { class: 'leise', style: 'max-width:75ch', text: 'Feedbackbögen für mündliche, praktische und Portfolio-Prüfungen: Bereiche mit Gewicht, darin Kriterien als Stufen (mit Punkten), Punkte, Abhaken (nur Information) oder Freitext. Eine Prüfung kopiert die Vorlage; spätere Änderungen an der Vorlage ändern laufende Prüfungen nicht.' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt', onclick: () => vorlageDialog(null) }, L.symbol('plus'), 'Vorlage'))),
      R.vorlagen.length ? el('div', { class: 'raster' }, R.vorlagen.map(v => el('button', { type: 'button', class: 'karte klassenkarte vorlage-karte', onclick: () => vorlageDialog(v) },
        el('div', { class: 'zeile' }, L.symbol('formular'), el('h3', { text: v.name })),
        el('div', { class: 'leise klein', text: (ARTEN.find(a => a[0] === v.art) || ['', v.art])[1] + ' · ' + v.struktur.bereiche.map(b => b.name + ' (' + fmt(b.gewicht) + ')').join(', ') }),
        el('div', { class: 'leise klein', text: v.struktur.bereiche.reduce((n, b) => n + b.kriterien.length, 0) + ' Kriterien' }))))
        : el('div', { class: 'leer', text: 'Noch keine Vorlage.' }));
  }

  const stufenText = st => (st || [{ name: 'nicht erkennbar', punkte: 0 }, { name: 'ansatzweise', punkte: 1 }, { name: 'überwiegend', punkte: 2 }, { name: 'vollständig', punkte: 3 }])
    .map(s => s.name + '=' + fmt(s.punkte)).join('; ');
  const stufenLesen = text => text.split(';').map(t => t.trim()).filter(Boolean).map(t => {
    const [name, punkte] = t.split('=');
    return { name: (name || '').trim(), punkte: (punkte || '').trim().replace(',', '.') };
  });

  async function vorlageDialog(v) {
    const name = el('input', { maxlength: 120, value: v ? v.name : '', placeholder: 'z. B. Präsentation + Fachgespräch' });
    const art = el('select', {}, ARTEN.map(([w, t]) => el('option', { value: w, text: t, selected: (v ? v.art : 'muendlich') === w ? true : null })));
    const bereicheOrt = el('div', { class: 'stapel', style: 'gap:10px' });
    const bereiche = [];
    const bereichNeu = b => {
      const bname = el('input', { maxlength: 80, value: b ? b.name : 'Bereich ' + (bereiche.length + 1), 'aria-label': 'Name des Bereichs' });
      const gewicht = el('input', { inputmode: 'decimal', value: b ? fmt(b.gewicht) : '1', style: 'width:80px', 'aria-label': 'Gewicht des Bereichs' });
      const kOrt = el('div', { class: 'stapel', style: 'gap:6px' });
      const kriterien = [];
      const kriteriumNeu = k => {
        const kname = el('input', { maxlength: 120, value: k ? k.name : '', placeholder: 'Kriterium', 'aria-label': 'Kriterium' });
        const typ = el('select', { 'aria-label': 'Art' }, [['stufen', 'Stufen'], ['punkte', 'Punkte'], ['haken', 'Abhaken'], ['text', 'Freitext']].map(([w, t]) =>
          el('option', { value: w, text: t, selected: (k ? k.typ : 'stufen') === w ? true : null })));
        const max = el('input', { inputmode: 'decimal', value: k && k.max ? fmt(k.max) : '', placeholder: 'max P', style: 'width:80px', 'aria-label': 'Höchstpunkte' });
        const kg = el('input', { inputmode: 'decimal', value: k && k.gewicht ? fmt(k.gewicht) : '', placeholder: 'Gewicht', style: 'width:80px', 'aria-label': 'Gewicht (freiwillig)' });
        const stufen = el('input', { value: stufenText(k && k.stufen), 'aria-label': 'Stufen (Name=Punkte; …)' });
        const stufenFeld = L.feld('Stufen (Name=Punkte; …)', stufen);
        const umschalten = () => { max.hidden = typ.value !== 'punkte'; stufenFeld.hidden = typ.value !== 'stufen'; kg.hidden = !['stufen', 'punkte'].includes(typ.value); };
        typ.addEventListener('change', umschalten);
        const eintrag = { key: k ? k.key : null, kname, typ, max, kg, stufen };
        const kasten = el('div', { class: 'kriterium-ed' }, el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, kname, typ, max, kg,
          el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Kriterium entfernen', onclick: () => { kriterien.splice(kriterien.indexOf(eintrag), 1); kasten.remove(); } }, L.symbol('zu'))),
          stufenFeld);
        umschalten();
        kriterien.push(eintrag);
        kOrt.appendChild(kasten);
      };
      (b ? b.kriterien : [null]).forEach(kriteriumNeu);
      const eintrag = { bname, gewicht, kriterien };
      const kasten = el('div', { class: 'bereich-ed' },
        el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, bname, el('span', { class: 'leise klein', text: 'Gewicht' }), gewicht,
          el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Bereich entfernen', onclick: () => { bereiche.splice(bereiche.indexOf(eintrag), 1); kasten.remove(); } }, L.symbol('muell'))),
        kOrt, el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => kriteriumNeu(null) }, L.symbol('plus'), 'Kriterium')));
      bereiche.push(eintrag);
      bereicheOrt.appendChild(kasten);
    };
    (v ? v.struktur.bereiche : [null]).forEach(bereichNeu);
    const r = await L.dialog({
      titel: v ? 'Vorlage bearbeiten' : 'Neue Vorlage', breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('div', { class: 'felder zwei' }, L.feld('Name', name), L.feld('Art', art)),
        el('p', { class: 'leise klein', text: 'Gewicht der Bereiche z. B. 40 und 60. Stufen bringen Punkte (Prozent = Punkte / höchste Stufe); ein Kriterium-Gewicht ist freiwillig. Abhaken und Freitext zählen nicht in die Note.' }),
        bereicheOrt,
        el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => bereichNeu(null) }, L.symbol('plus'), 'Bereich')),
        v ? el('div', {}, L.nebenknopf('Vorlage löschen …', async () => {
          const ok = await L.dialog({ titel: 'Vorlage löschen?', knopf: 'Löschen', gefaehrlich: true, inhalt: el('p', { text: 'Prüfungen, die sie benutzt haben, behalten ihre Kopie.' }),
            speichern: () => L.api('POST', '/api/vorlage/' + v.id + '/loeschen', {}) });
          if (ok) vorlagenZeigen();
        })) : null),
      speichern: () => L.api('POST', v ? '/api/vorlage/' + v.id : '/api/vorlage', { name: name.value, art: art.value, struktur: { bereiche: bereiche.map(b => ({
        name: b.bname.value, gewicht: b.gewicht.value.replace(',', '.'),
        kriterien: b.kriterien.map(k => ({ key: k.key, name: k.kname.value, typ: k.typ.value, max: k.max.value.replace(',', '.') || null,
          gewicht: k.kg.value.replace(',', '.') || null, stufen: k.typ.value === 'stufen' ? stufenLesen(k.stufen.value) : undefined })) })) } }),
    });
    if (r) vorlagenZeigen();
  }

  // --- Notenschluessel: Konferenz (nur ansehen), eigene, persoenlicher Standard ---

  async function schluesselZeigen() {
    const R = await L.api('GET', '/api/pruefungen');
    const std = el('select', { 'aria-label': 'Persönlicher Standard', style: 'width:auto', onchange: async () => {
      try { await L.api('POST', '/api/notenschluessel/standard', { notenschluessel_id: std.value || null }); L.meldung('Standard gespeichert.'); } catch (e) { L.meldung(e.message, true); }
    } }, el('option', { value: '', text: 'kein Standard (Konferenzschlüssel des Bildungsgangs)' }),
    R.schluessel.map(s => el('option', { value: s.id, text: s.name + ' · ' + s.systemname, selected: R.standard === s.id ? true : null })));
    const karte = s => el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, L.symbol('schluessel'), el('b', { text: s.name }), el('span', { class: 'chip' + (s.art === 'eigen' ? ' gelb' : ''), text: s.art === 'eigen' ? 'eigener' : 'Konferenz' }),
        el('span', { class: 'chip', text: s.systemname }), R.standard === s.id ? el('span', { class: 'chip blau', text: 'dein Standard' }) : null),
      el('div', { class: 'leise klein mono', text: s.stufen.slice(0, 6).map(st => st.replace('-', '−') + ' ab ' + s.grenzen[st] + ' %').join(' · ') + (s.stufen.length > 6 ? ' …' : '') }),
      el('div', { class: 'zeile' },
        s.art === 'eigen' ? el('button', { type: 'button', class: 'klein', onclick: () => Admin.schluesselBearbeiten(null, s, { eigen: true, danach: schluesselZeigen }) }, L.symbol('stift'), 'bearbeiten') : null,
        el('button', { type: 'button', class: 'klein', onclick: async () => {
          try { await L.api('POST', '/api/notenschluessel/' + s.id + '/kopieren', {}); L.meldung('Als eigenen Schlüssel kopiert.'); schluesselZeigen(); } catch (e) { L.meldung(e.message, true); }
        } }, L.symbol('kopie'), 'als eigenen kopieren')));
    L.setzen(ort,
      el('div', { class: 'karte stapel', style: 'max-width:760px' }, el('h2', { text: 'Dein Standard' }),
        el('p', { class: 'leise klein', text: 'Reihenfolge, welcher Schlüssel in einer Prüfung gilt: in der Prüfung gewählt → Schlüssel der Klasse → dein Standard → Konferenzschlüssel des Bildungsgangs. Abgeschlossene Prüfungen ändern sich nicht mehr.' }),
        std),
      el('div', { class: 'zeile' }, el('h2', { text: 'Schlüssel' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt', onclick: () => Admin.schluesselBearbeiten(null, null, { eigen: true, danach: schluesselZeigen }) }, L.symbol('plus'), 'Eigener Schlüssel'))),
      el('div', { class: 'zwei-spalten' }, R.schluessel.map(karte)));
  }

  // Aus dem Wochenplan: Pruefung mit Klasse, Gruppe, Tag und Block vorbelegt
  async function ausWochenplan(b, danach) {
    await grunddaten();
    const sj = G.schuljahre.find(j => j.beginn <= b.datum && b.datum <= j.ende);
    if (!sj) { L.meldung('Dieser Tag liegt in keinem Schuljahr.', true); return; }
    await pruefungDialog(null, null, { klasse_id: b.klasse.id, gruppe_id: b.gruppe ? b.gruppe.id : null, schuljahr_id: sj.id, datum: b.datum, beginn: b.beginn },
      id => { if (danach) danach(); L.meldung('Prüfung angelegt.'); void id; });
  }

  return { zeigen, ausWochenplan };
})();
