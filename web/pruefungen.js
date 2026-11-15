'use strict';
// Pruefungen und Bewertung (Stufe D1). Reiter: Pruefungen · Schuelerlisten · Vorlagen · Notenschluessel.
// Eine Pruefung: fester Termin (belegt Bloecke der Planung) oder Fenster mit Frist; Erfassung als Punkte je Aufgabe,
// Gesamtpunkte oder Feedbackbogen (je Schueler im Overlay). Jede Eingabe wird sofort gespeichert; Note und Rechenweg
// rechnet der Server ueber den gueltigen Notenschluessel.
const Pruefungen = (() => {
  const el = L.el;
  const ARTEN = [['schriftlich', 'schriftlich'], ['muendlich', 'mündlich'], ['praktisch', 'praktisch'], ['portfolio', 'Portfolio']];
  const STAND = { geplant: ['geplant', ''], angekuendigt: ['angekündigt', 'blau'], durchgefuehrt: ['durchgeführt', 'gelb'], ausgewertet: ['abgeschlossen', 'gruen'] };
  const ERFASSUNG = { aufgaben: 'Punkte je Aufgabe', gesamt: 'Gesamtpunkte', bogen: 'Feedbackbogen', checkliste: 'Checkliste (Labor)' };
  const hatTeams = p => p.erfassung === 'checkliste' || (p.erfassung === 'bogen' && p.struktur.bereiche.some(b => b.team));
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
        el('span', { class: 'rechts zeile' },
          el('button', { type: 'button', title: 'Ergebnisse eines Moodle-Tests als neue Prüfung übernehmen', onclick: () => moodleImport({ klasse_id: wahl.klasse }) }, L.symbol('hoch'), 'Aus Moodle'),
          el('button', { type: 'button', class: 'haupt', onclick: () => pruefungDialog(null, R, { klasse_id: wahl.klasse, gruppe_id: wahl.gruppe, schuljahr_id: wahl.schuljahr }) }, L.symbol('plus'), 'Prüfung'))),
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
    // Bogen: Bereiche, die fuers ganze Team gelten
    const teamOrt = el('div', { class: 'stapel', style: 'gap:4px' });
    let teamHaken = [];
    const teamBereicheZeigen = () => {
      const v = R.vorlagen.find(x => String(x.id) === vorlage.value);
      const bereiche = v ? v.struktur.bereiche : p && p.erfassung === 'bogen' ? p.struktur.bereiche : [];
      teamHaken = bereiche.map(b => el('input', { type: 'checkbox', checked: !v && b.team ? true : null }));
      L.setzen(teamOrt, bereiche.length ? [el('span', { class: 'leise klein', text: 'Gilt fürs ganze Team (Teams legst du in der Prüfung an):' }),
        bereiche.map((b, i) => el('label', { class: 'haken' }, teamHaken[i], b.name))] : []);
    };
    vorlage.addEventListener('change', teamBereicheZeigen);
    teamBereicheZeigen();
    teilBogen.appendChild(teamOrt);
    // Checkliste: Versuche mit Haken (je Haken Punkte), Versuch im Team oder einzeln
    const versucheOrt = el('div', { class: 'stapel', style: 'gap:10px' });
    const versuche = [];
    const versuchNeu = v => {
      const name = el('input', { maxlength: 80, value: v ? v.name : 'Versuch ' + (versuche.length + 1), 'aria-label': 'Name des Versuchs' });
      let team = v ? !!v.team : true;
      const hakenOrt = el('div', { class: 'stapel', style: 'gap:4px' });
      const eintrag = { name, haken: [], get team() { return team; } };
      const hakenNeu = h => {
        const hn = el('input', { maxlength: 120, value: h ? h.name : '', placeholder: 'z. B. Aufbau abgenommen', 'aria-label': 'Haken' });
        const hp = el('input', { inputmode: 'decimal', value: h ? fmt(h.max) : '1', style: 'width:70px', 'aria-label': 'Punkte' });
        const he = { key: h ? h.key : null, hn, hp };
        const zeile = el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, el('span', { class: 'leise', text: '☐' }), hn, hp, el('span', { class: 'leise klein', text: 'P' }),
          el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Haken entfernen', onclick: () => { eintrag.haken.splice(eintrag.haken.indexOf(he), 1); zeile.remove(); } }, L.symbol('zu')));
        eintrag.haken.push(he);
        hakenOrt.appendChild(zeile);
      };
      (v ? v.kriterien : [{ name: 'Aufbau', max: 1 }, { name: 'Messung', max: 1 }, { name: 'Protokoll', max: 2 }]).forEach(hakenNeu);
      const karte = el('div', { class: 'ka stapel', style: 'gap:6px' },
        el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, name,
          segment([['team', 'im Team'], ['einzeln', 'einzeln']], team ? 'team' : 'einzeln', w => { team = w === 'team'; }),
          el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Versuch entfernen', onclick: () => { versuche.splice(versuche.indexOf(eintrag), 1); karte.remove(); } }, L.symbol('zu'))),
        hakenOrt,
        el('div', {}, el('button', { type: 'button', class: 'leicht klein', onclick: () => hakenNeu(null) }, L.symbol('plus'), 'Haken')));
      versuche.push(eintrag);
      versucheOrt.appendChild(karte);
    };
    (p && p.erfassung === 'checkliste' ? p.struktur.bereiche : [null]).forEach(versuchNeu);
    const testat = el('input', { type: 'checkbox', checked: p && p.struktur.testat ? true : null });
    const teilCheckliste = el('div', { class: 'stapel', style: 'gap:8px' }, versucheOrt,
      el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'klein', onclick: () => versuchNeu(null) }, L.symbol('plus'), 'Versuch'),
        el('label', { class: 'haken' }, testat, 'nur Testat (abhaken ohne Note)')),
      el('p', { class: 'leise klein', text: 'Jeder Haken bringt seine Punkte; Note = abgehakte Punkte / alle Punkte. „Im Team“: ein Haken gilt für alle im Team.' }));
    const zeigeErfassung = w => {
      erfassung = w; teilAufgaben.hidden = w !== 'aufgaben'; teilGesamt.hidden = w !== 'gesamt'; teilBogen.hidden = w !== 'bogen'; teilCheckliste.hidden = w !== 'checkliste';
      if (w === 'checkliste' && !p && form === 'termin') { const b = segForm.querySelector('[data-w="fenster"]'); if (b) b.click(); }   // Laborreihe: meist Fenster mit Frist
    };
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
        el('div', { class: 'stapel', style: 'gap:8px' }, el('span', { class: 'etikett', text: 'Erfassung' }), segErfassung, teilAufgaben, teilGesamt, teilBogen, teilCheckliste),
        L.feld('Notenschlüssel', schl, 'Ein eigener Schlüssel erscheint in der Prüfung als abweichender Schlüssel.'),
        p ? el('div', {}, L.nebenknopf('Prüfung löschen …', () => loeschen(p))) : null),
      speichern: () => L.api('POST', p ? '/api/pruefung/' + p.id : '/api/pruefung', Object.assign(p ? {} : { klasse_id: vorgabe.klasse_id, gruppe_id: vorgabe.gruppe_id, schuljahr_id: vorgabe.schuljahr_id }, {
        titel: titel.value, art: art.value, lernfeld_id: lf.value || null, form, datum: datum.value, beginn: block.value, bloecke: Number(bloecke.value),
        teilung, termine: teilung === 'getrennt' ? gruppenTermine.map(t => ({ gruppe_id: t.g.id, datum: t.gDatum.value, beginn: t.gBlock.value })) : undefined,
        fenster_von: von.value, fenster_bis: bis.value, erfassung, notenschluessel_id: schl.value || null, stand: stand.value,
        aufgaben: erfassung === 'aufgaben' ? aufgaben.map(a => ({ key: a.key, name: a.name.value, max: a.max.value })) : undefined,
        max_punkte: erfassung === 'gesamt' ? maxPunkte.value : undefined,
        vorlage_id: erfassung === 'bogen' && vorlage.value ? Number(vorlage.value) : undefined,
        team_bereiche: erfassung === 'bogen' ? teamHaken.map((h, i) => h.checked ? i : null).filter(i => i !== null) : undefined,
        versuche: erfassung === 'checkliste' ? versuche.map(v => ({ name: v.name.value, team: v.team,
          haken: v.haken.map(h => ({ key: h.key, name: h.hn.value, punkte: h.hp.value.replace(',', '.') })) })) : undefined,
        testat: erfassung === 'checkliste' ? testat.checked : undefined })),
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
    if (PM.ort && (!E || E.pruefung.id !== pid)) { clearInterval(PM.takt); PM.takt = null; PM.ort.remove(); PM.ort = null; document.body.classList.remove('pm-offen'); }
    E = await L.api('GET', '/api/pruefung/' + pid);
    detailZeichnen();
  }

  function schluesselText() {
    if (E.pruefung.struktur.testat) return el('span', { class: 'chip', text: 'Testat · ohne Note' });
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
          !fertig && E.schueler.length ? el('button', { type: 'button', onclick: pruefungsmodus }, L.symbol('uhr'), 'Prüfungsmodus') : null,
          !fertig ? el('button', { type: 'button', onclick: async () => pruefungDialog(p, null, null, () => detailZeigen(p.id)) }, L.symbol('stift'), 'Bearbeiten') : null,
          fertig ? el('button', { type: 'button', onclick: oeffnen }, L.symbol('undo'), 'Wieder öffnen')
            : el('button', { type: 'button', class: 'haupt', onclick: abschliessen }, L.symbol('ok'), 'Abschließen'))),
      el('div', { class: 'zeile leise klein' }, el('span', { text: p.artname + ' · ' + ERFASSUNG[p.erfassung] + ' · ' + wannText(p) }), schluesselText(),
        el('span', { text: E.herkunft })),
      el('div', { class: 'zeile' },
        segment([['bewerten', 'Bewerten']].concat(hatTeams(p) ? [['teams', 'Teams' + (p.teams.length ? ' (' + p.teams.length + ')' : '')]] : [],
          [['fragen', 'Fragen' + (p.fragen.length ? ' (' + p.fragen.length + ')' : '')], ['auswertung', 'Auswertung'], ['export', 'Export']]),
          reiter, w => { reiter = w; detailZeichnen(); }),
        kopfStatistik(st)),
      fertig ? el('div', { class: 'banner', text: 'Abgeschlossen: Der Notenschlüssel ist festgehalten, Bewertungen sind gesperrt. „Wieder öffnen“ hebt das auf.' }) : null,
      p.hinweise && p.hinweise.length ? el('div', { class: 'banner warnung' }, p.hinweise.map(h => el('div', { text: h }))) : null,
      rumpf);
    zeichneRumpf(rumpf);
  }

  function kopfStatistik(st) {
    if (E.pruefung.erfassung === 'checkliste') {
      const fertig = E.schueler.filter(z => z.aktiv && !z.fehlt && z.versuche.every(v => v.erledigt === v.gesamt)).length;
      return el('span', { class: 'zeile pr-statistik' },
        el('span', { class: 'leise klein', text: fertig + ' von ' + st.schueler + ' haben alle Versuche' + (st.fehlt ? ' · ' + st.fehlt + ' gefehlt' : '') }),
        st.schnitt !== null ? el('span', { class: 'chip blau', text: 'Ø ' + fmt(st.schnitt, 2) + ' · ' + fmt(st.prozent) + ' %' }) : null);
    }
    return el('span', { class: 'zeile pr-statistik' },
      el('span', { class: 'leise klein', text: st.bewertet + ' von ' + st.schueler + ' bewertet' + (st.fehlt ? ' · ' + st.fehlt + ' gefehlt' : '') }),
      st.schnitt !== null ? el('span', { class: 'chip blau', text: 'Ø ' + fmt(st.schnitt, 2) + ' · ' + fmt(st.prozent) + ' %' }) : null);
  }

  function zeichneRumpf(rumpf) {
    if (!E.schueler.length) {
      return L.setzen(rumpf, el('div', { class: 'leer' }, 'Für diese Klasse gibt es noch keine Schülerliste. ', el('a', { href: '#pruefungen-schueler', text: 'Schülerliste anlegen' })));
    }
    if (reiter === 'teams' && !hatTeams(E.pruefung)) reiter = 'bewerten';
    if (reiter === 'fragen') return L.setzen(rumpf, fragenAnsicht());
    if (reiter === 'export') { X = null; return L.setzen(rumpf, exportAnsicht()); }
    L.setzen(rumpf, reiter === 'auswertung' ? auswertung() : reiter === 'teams' ? teamsAnsicht()
      : E.pruefung.erfassung === 'checkliste' ? checklisteMatrix() : bewertenTabelle());
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
        z.notiz ? el('p', { class: 'klein' }, el('b', { text: 'Notiz: ' }), z.notiz) : null,
        el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => L.herunterladen('/api/pruefung/' + E.pruefung.id + '/rueckmeldung.pdf?schueler=' + z.id).catch(e => L.meldung(e.message, true)) },
          L.symbol('formular'), 'Rückmeldebogen (PDF)'))),
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
        z.team ? el('span', { class: 'chip klein team', text: z.team }) : null,
        z.dauer !== null && z.dauer !== undefined ? el('span', { class: 'leise klein mono', title: 'Dauer im Prüfungsmodus', text: ' ⏱ ' + mmss(z.dauer) }) : null,
        z.protokoll && z.protokoll.length ? el('span', { class: 'leise klein', title: z.protokoll.map(x => x.text + (x.stufe !== null ? ' (' + x.stufe + '/4)' : '')).join('\n'), text: ' · ' + z.protokoll.length + ' Fragen' }) : null,
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
      p.erfassung === 'gesamt' && !fertig ? el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'klein', onclick: () => moodleImport({ pruefung_id: p.id }) },
        L.symbol('hoch'), 'Moodle-Ergebnisse übernehmen'), el('span', { class: 'leise klein', text: 'aus dem Bericht „Antworten“ eines Moodle-Tests' })) : null,
      el('div', { class: 'r-scroll' }, el('table', { class: 'liste bewerten' }, el('thead', {}, kopf), el('tbody', {}, zeilen))),
      el('p', { class: 'leise klein', text: p.erfassung === 'bogen'
        ? '„Bogen“ öffnet den Feedbackbogen des Schülers; jede Eingabe wird sofort gespeichert. Tipp auf die Note zeigt den Rechenweg.'
        : 'Eintippen und mit Tab oder Enter weiter; jede Eingabe wird sofort gespeichert. Leeres Feld = nicht bewertet. Tipp auf die Note zeigt den Rechenweg; eine gelb umrandete Note hat unbewertete Aufgaben.' }));
  }

  // --- Teams einer Pruefung ---
  async function teamAktion(pfad, daten) {
    try { E = await L.api('POST', '/api/pruefung/' + E.pruefung.id + pfad, daten || {}); detailZeichnen(); return true; }
    catch (e) { L.meldung(e.message, true); return false; }
  }

  function teamsAnsicht() {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    const name = id => (E.schueler.find(z => z.id === id) || {}).name || '?';
    const ohne = E.schueler.filter(z => z.aktiv && !z.team_id);
    const groesse = el('select', { 'aria-label': 'Teamgröße', style: 'width:auto' }, [2, 3, 4, 5].map(n => el('option', { value: n, text: n + 'er-Teams', selected: n === 3 ? true : null })));
    const bilden = async () => {
      if (p.teams.length && !await L.dialog({ titel: 'Teams neu bilden?', knopf: 'Neu bilden', gefaehrlich: true, speichern: () => true,
        inhalt: el('p', { text: 'Die bisherigen ' + p.teams.length + ' Teams und ihre Team-Haken bzw. Teamwerte werden ersetzt.' }) })) return;
      teamAktion('/teams/bilden', { groesse: Number(groesse.value) });
    };
    return el('div', { class: 'stapel' },
      !fertig ? el('div', { class: 'zeile' },
        el('button', { type: 'button', onclick: () => teamDialog(null) }, L.symbol('plus'), 'Team'),
        el('span', { class: 'leise klein', text: 'oder zufällig:' }), groesse, el('button', { type: 'button', onclick: bilden }, 'Teams bilden')) : null,
      p.teams.length ? el('div', { class: 'raster' }, p.teams.map(t => el('div', { class: 'karte stapel', style: 'gap:6px' },
        el('div', { class: 'zeile' }, el('h3', { text: t.name }), el('span', { class: 'leise klein', text: t.mitglieder.length + ' Schüler' }),
          !fertig ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Team bearbeiten', onclick: () => teamDialog(t) }, L.symbol('stift'))) : null),
        el('div', { class: 'zeile' }, t.mitglieder.map(id => el('span', { class: 'chip', text: name(id) }))))))
        : el('div', { class: 'leer', text: 'Noch keine Teams. Lege sie an oder lass sie zufällig bilden. Ohne Team wird jeder einzeln bewertet.' }),
      ohne.length && p.teams.length ? el('p', { class: 'leise klein', text: 'Ohne Team (wird einzeln bewertet): ' + ohne.map(z => z.name).join(' · ') }) : null);
  }

  async function teamDialog(t) {
    const p = E.pruefung;
    const name = el('input', { maxlength: 60, value: t ? t.name : 'Team ' + (p.teams.length + 1) });
    const haken = E.schueler.filter(z => z.aktiv || (t && t.mitglieder.includes(z.id))).map(z => {
      const c = el('input', { type: 'checkbox', checked: t && t.mitglieder.includes(z.id) ? true : null, value: z.id });
      return el('label', { class: 'haken' }, c, z.name, z.team_id && (!t || z.team_id !== t.id) ? el('span', { class: 'leise klein', text: ' (jetzt ' + z.team + ')' }) : null);
    });
    const weitere = t ? [{ text: 'Team auflösen', klasse: 'warnen', speichern: () => L.api('POST', '/api/pruefung/' + p.id + '/team/' + t.id + '/loeschen', {}) }] : [];
    const r = await L.dialog({
      titel: t ? 'Team bearbeiten' : 'Neues Team', weitere,
      inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, L.feld('Name', name),
        el('span', { class: 'etikett', text: 'Mitglieder' }), el('div', { class: 'stapel team-wahl', style: 'gap:2px' }, haken),
        el('p', { class: 'leise klein', text: 'Wer schon in einem anderen Team ist, wechselt hierher.' })),
      speichern: () => L.api('POST', '/api/pruefung/' + p.id + '/team' + (t ? '/' + t.id : ''), {
        name: name.value, schueler_ids: haken.map(l => l.querySelector('input')).filter(c => c.checked).map(c => Number(c.value)) }),
    });
    if (r) { E = r.pruefung ? r : await L.api('GET', '/api/pruefung/' + p.id); detailZeichnen(); }
  }

  // --- Checkliste: Matrix Schueler (nach Teams) x Versuche ---
  function checklisteMatrix() {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    const versuche = p.struktur.bereiche;
    const ordnung = [];
    p.teams.forEach(t => E.schueler.filter(z => z.team_id === t.id).forEach(z => ordnung.push(z)));
    E.schueler.filter(z => !z.team_id).forEach(z => ordnung.push(z));
    const kopf = el('tr', {}, el('th', { text: 'Schüler' }),
      versuche.map((v, i) => el('th', { class: 'zahl', title: v.kriterien.map(k => k.name + ' (' + fmt(k.max) + ' P)').join(', ') },
        v.name, el('br'), el('span', { class: 'leise', text: (v.team ? 'Team · ' : 'einzeln · ') + E.statistik.fortschritt[i] + ' fertig' }))),
      el('th', { class: 'zahl', text: '%' }), p.struktur.testat ? null : el('th', { text: 'Note' }), el('th', { text: 'fehlt' }));
    let teamVorher = null;
    const zeilen = [];
    ordnung.forEach(z => {
      if (z.team_id && z.team_id !== teamVorher) {
        const t = p.teams.find(x => x.id === z.team_id);
        zeilen.push(el('tr', { class: 'team-kopf' }, el('td', { colspan: 999 }, el('span', { class: 'chip klein team', text: t.name }),
          el('span', { class: 'leise klein', text: ' Team-Haken gelten für alle ' + t.mitglieder.length }))));
      }
      teamVorher = z.team_id;
      const tr = el('tr', { class: z.aktiv ? null : 'aus' }, el('td', {}, el('b', { text: z.name }), z.gruppe ? el('span', { class: 'chip klein gr', text: z.gruppe }) : null));
      versuche.forEach((v, i) => {
        const f = z.versuche[i];
        const art = f.erledigt === f.gesamt ? 'fertig' : f.erledigt ? 'teil' : 'offen';
        tr.appendChild(el('td', { class: 'zahl' }, el('button', { type: 'button', class: 'versuch ' + art, disabled: z.fehlt ? true : null,
          title: v.name + ': ' + v.kriterien.map(k => (z.werte[k.key] ? '✓ ' : '☐ ') + k.name).join(', '),
          onclick: () => abhaken(z.id, i) }, art === 'fertig' ? '✓' : f.erledigt + '/' + f.gesamt)));
      });
      tr.appendChild(el('td', { class: 'zahl mono', text: z.prozent !== null && !z.fehlt ? fmt(z.prozent) : '–' }));
      if (!p.struktur.testat) tr.appendChild(noteZelle(z));
      const fehlt = el('input', { type: 'checkbox', checked: z.fehlt ? true : null, disabled: fertig ? true : null, 'aria-label': z.name + ' fehlt' });
      fehlt.addEventListener('change', async () => { if (await speichern(z.id, { fehlt: fehlt.checked })) detailZeichnen(); });
      tr.appendChild(el('td', {}, fehlt));
      zeilen.push(tr);
    });
    return el('div', { class: 'stapel', style: 'gap:8px' },
      el('div', { class: 'r-scroll' }, el('table', { class: 'liste bewerten checkliste' }, el('thead', {}, kopf), el('tbody', {}, zeilen))),
      el('p', { class: 'leise klein', text: 'Tipp auf einen Versuch: Haken setzen. ✓ = alle Haken, 1/3 = angefangen. Bei Team-Versuchen gilt der Haken für das ganze Team.' + (hatTeams(p) && !p.teams.length ? ' Teams legst du im Reiter „Teams“ an.' : '') }));
  }

  async function abhaken(sid, i) {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    const v = p.struktur.bereiche[i];
    const z = E.schueler.find(x => x.id === sid);
    const t = v.team && z.team_id ? p.teams.find(x => x.id === z.team_id) : null;
    const wer = t ? t.mitglieder.map(id => (E.schueler.find(x => x.id === id) || {}).name).filter(Boolean).join(', ') : z.name;
    await L.dialog({
      titel: v.name, knopf: 'Fertig', abbrechen: null, fokus: false, speichern: () => true,
      inhalt: el('div', { class: 'stapel', style: 'gap:8px' },
        el('p', { class: 'klein' }, t ? el('span', { class: 'chip klein team', text: t.name }) : null, ' ' + wer),
        el('div', { class: 'stapel abhaken' }, v.kriterien.map(k => el('label', { class: 'haken gross' },
          el('input', { type: 'checkbox', checked: z.werte[k.key] ? true : null, disabled: fertig ? true : null,
            onchange: ev => speichern(sid, { werte: { [k.key]: ev.target.checked ? true : null } }) }),
          el('span', { text: k.name }), el('span', { class: 'leise klein', text: fmt(k.max) + ' P' })))),
        v.team && !z.team_id ? el('p', { class: 'leise klein', text: 'Ohne Team: der Haken gilt nur für diesen Schüler.' }) : null),
    });
    detailZeichnen();
  }

  // --- Moodle-Ergebnisse uebernehmen (Bericht "Antworten" als JSON oder CSV) ---
  // ziel: { pruefung_id } (vorhandene Pruefung mit Gesamtpunkten) oder { klasse_id } (neue Pruefung aus der Datei)
  async function moodleImport(ziel) {
    let V = null, text = '', dateiname = '';
    const datei = el('input', { type: 'file', accept: '.json,.csv,.txt,application/json,text/csv' });
    const titel = el('input', { maxlength: 120, placeholder: 'Titel der Prüfung' });
    const ort = el('div', { class: 'stapel', style: 'gap:8px' });
    const auswahl = {};
    const zeichne = () => {
      const s = V.schueler;
      const vergeben = () => Object.values(auswahl).map(x => x.value).filter(Boolean);
      const zeilen = V.zeilen.map(z => {
        const sel = el('select', { class: z.schueler_id && !z.sicher ? 'unsicher' : null, 'aria-label': 'Zuordnung für ' + z.name },
          el('option', { value: '', text: '– nicht übernehmen –' }),
          s.map(x => el('option', { value: x.id, text: x.name + (x.aktiv ? '' : ' (ausgetreten)'), selected: x.id === z.schueler_id ? true : null })));
        sel.addEventListener('change', () => { sel.classList.remove('unsicher'); pruefeDoppelt(); });
        auswahl[z.schluessel] = sel;
        return el('tr', {},
          el('td', {}, el('b', { text: z.name }), z.anzahl > 1 ? el('span', { class: 'leise klein', text: ' · ' + z.anzahl + ' Versuche, bester zählt' }) : null),
          el('td', { class: 'mono zahl', text: z.bewertung === null ? '–' : fmt(z.bewertung, 2) + ' / ' + fmt(V.max) }),
          el('td', { class: 'klein' }, z.datum ? tagKurz(z.datum) : '', z.nachgeschrieben ? el('span', { class: 'chip gelb klein', text: 'nachgeschrieben' }) : null),
          el('td', {}, sel));
      });
      const doppelt = el('div', { class: 'banner warnung klein', hidden: true });
      const pruefeDoppelt = () => {
        const v = vergeben();
        const mehrfach = s.filter(x => v.filter(y => Number(y) === x.id).length > 1).map(x => x.name);
        doppelt.textContent = mehrfach.length ? 'Mehrfach zugeordnet: ' + mehrfach.join(', ') : '';
        doppelt.hidden = !mehrfach.length;
      };
      const unsicher = V.zeilen.filter(z => z.schueler_id && !z.sicher).length;
      const ohne = V.zeilen.filter(z => !z.schueler_id).length;
      L.setzen(ort,
        el('p', { class: 'klein' }, el('b', { text: V.zeilen.length + ' Personen' }),
          ' · Höchstwert ' + fmt(V.max) + (V.pruefung ? ' → umgerechnet auf ' + fmt(V.pruefung.max_punkte) + ' Punkte von „' + V.pruefung.titel + '“' : '') +
          (V.termin ? ' · Prüfungstag ' + tagKurz(V.termin) : '') + (V.uebersprungen ? ' · ' + V.uebersprungen + ' nicht beendete Versuche übersprungen' : '')),
        !V.pruefung ? L.feld('Neue Prüfung', titel, 'Gesamtpunkte (max. ' + fmt(V.max) + '), fester Termin am Prüfungstag im passenden Block') : null,
        unsicher || ohne ? el('div', { class: 'banner klein', text: (unsicher ? unsicher + ' Zuordnung(en) nur vorgeschlagen (gelb) – bitte prüfen. ' : '') +
          (ohne ? ohne + ' ohne passenden Namen in der Schülerliste – wähle den Schüler oder „nicht übernehmen“.' : '') }) : null,
        el('div', { class: 'r-scroll', style: 'max-height:50vh' }, el('table', { class: 'liste moodle-import' },
          el('thead', {}, el('tr', {}, ['Name in Moodle', 'Bewertung', 'Tag', 'Schüler'].map(t => el('th', { text: t })))), el('tbody', {}, zeilen))),
        doppelt,
        el('p', { class: 'leise klein', text: 'Übernommen werden die Bewertung (bester Versuch) sowie Beginn und Dauer; Nachschreiber bekommen einen Vermerk in der Notiz. Die Antworttexte bleiben in Moodle.' }));
      titel.value = titel.value || V.titel;
    };
    datei.addEventListener('change', async () => {
      const f = datei.files[0];
      if (!f) return;
      dateiname = f.name;
      text = await f.text();
      L.setzen(ort, el('p', { class: 'leise', text: 'Lese …' }));
      try { V = await L.api('POST', '/api/moodle/vorschau', Object.assign({ text, dateiname }, ziel)); zeichne(); }
      catch (e) { V = null; L.setzen(ort, el('div', { class: 'banner warnung', text: e.message })); }
    });
    const r = await L.dialog({
      titel: ziel.pruefung_id ? 'Moodle-Ergebnisse übernehmen' : 'Neue Prüfung aus Moodle', knopf: 'Übernehmen', breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('p', { class: 'leise klein', text: 'In Moodle im Test unter Ergebnisse → „Antworten“ (oder „Bewertungen“) den Bericht als JSON oder CSV herunterladen und hier wählen.' }),
        datei, ort),
      speichern: () => {
        if (!V) throw new Error('Bitte zuerst die Moodle-Datei wählen.');
        const zuordnung = Object.fromEntries(Object.entries(auswahl).map(([k, sel]) => [k, sel.value ? Number(sel.value) : null]));
        return L.api('POST', '/api/moodle/uebernehmen', Object.assign({ text, dateiname, zuordnung, titel: titel.value }, ziel));
      },
    });
    if (!r) return;
    L.meldung(r.uebernommen + ' Bewertung(en) übernommen' + (r.ohne_zuordnung ? ', ' + r.ohne_zuordnung + ' nicht übernommen' : '') + '.');
    if (location.hash === '#pruefung-' + r.pruefung_id) detailZeigen(r.pruefung_id);
    else location.hash = '#pruefung-' + r.pruefung_id;
  }

  // --- Reiter Export: Notenspalte (Excel), PDF, Moodle ---
  let X = null;   // Exportdaten der Pruefung

  async function kopieren(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {   // ohne Zwischenablage-Recht: Text zum Markieren anbieten
      const t = el('textarea', { rows: 10, readonly: true });
      t.value = text;
      L.dialog({ titel: 'Zum Kopieren markieren', knopf: 'Schließen', abbrechen: null, speichern: () => true,
        inhalt: el('div', { class: 'stapel' }, el('p', { class: 'leise klein', text: 'Strg+A, Strg+C – dann in Excel einfügen.' }), t) });
      setTimeout(() => { t.focus(); t.select(); }, 50);
      return false;
    }
  }

  function exportAnsicht() {
    const p = E.pruefung;
    const ort = el('div', { class: 'stapel' }, el('p', { class: 'leise', text: 'Lade …' }));
    const zeichne = () => {
      const mitNote = X.notenspalte.filter(z => z.note).length;
      const download = async (pfad, knopf) => {
        knopf.disabled = true;
        try { await L.herunterladen('/api/pruefung/' + p.id + pfad); } catch (e) { L.meldung(e.message, true); }
        knopf.disabled = false;
      };
      const knopf = (text, sym, pfad) => { const b = el('button', { type: 'button' }, L.symbol(sym), text); b.addEventListener('click', () => download(pfad, b)); return b; };
      L.setzen(ort, el('div', { class: 'raster export' },
        el('div', { class: 'karte stapel' }, el('h3', { text: 'Excel-Notenliste' }),
          el('p', { class: 'leise klein', text: 'Alle ' + X.notenspalte.length + ' Schüler der Liste alphabetisch, Note als Dezimalzahl (' + mitNote + ' mit Note). Gefehlt oder ohne Note = leere Zelle. In Excel die erste Zelle der Spalte anklicken und einfügen.' }),
          el('div', { class: 'zeile' },
            el('button', { type: 'button', class: 'haupt', onclick: async () => { if (await kopieren(X.notenspalte.map(z => z.note).join('\n'))) L.meldung('Notenspalte kopiert (' + X.notenspalte.length + ' Zeilen).'); } }, L.symbol('kopie'), 'Noten kopieren'),
            el('button', { type: 'button', onclick: async () => { if (await kopieren(X.notenspalte.map(z => z.name + '\t' + z.note).join('\n'))) L.meldung('Namen und Noten kopiert.'); } }, 'Name + Note kopieren')),
          el('div', { class: 'notenspalte' }, el('table', { class: 'liste' }, el('tbody', {}, X.notenspalte.map(z => el('tr', { class: z.aktiv ? null : 'aus' },
            el('td', { text: z.name }), el('td', { class: 'mono zahl', text: z.note || (z.fehlt ? 'fehlt' : '') }))))))),
        el('div', { class: 'karte stapel' }, el('h3', { text: 'PDF zum Abheften' }),
          el('p', { class: 'leise klein', text: 'Ergebnisliste mit Notenspiegel für deine Akte; Rückmeldebögen je Schüler (eine Seite, ohne Daten anderer, mit Unterschriftszeilen) zum Aushändigen.' }),
          el('div', { class: 'zeile' }, knopf('Ergebnisliste', 'liste', '/ergebnis.pdf'), knopf('Rückmeldebögen', 'formular', '/rueckmeldung.pdf')),
          el('p', { class: 'leise klein', text: 'Einen einzelnen Bogen gibt es auch über den Rechenweg (Tipp auf die Note).' })),
        el('div', { class: 'karte stapel' }, el('h3', { text: 'Moodle-Bewertungsbuch' }),
          el('p', { class: 'leise klein', text: 'CSV mit E-Mail-Adresse, Bewertung (Prozent) und Feedback (Note). In Moodle: Bewertungen → Import → CSV-Datei; Zuordnung „E-Mail-Adresse“ ↔ „E-Mail-Adresse“, dann die Spalte „Bewertung“ dem Bewertungsaspekt zuordnen (Höchstwert 100).' }),
          X.ohne_email.length ? el('div', { class: 'banner warnung klein', text: 'Ohne E-Mail-Adresse (fehlt in der CSV): ' + X.ohne_email.join(', ') + '. Ergänze sie in der Schülerliste.' }) : null,
          el('div', {}, knopf('CSV herunterladen', 'hoch', '/moodle.csv')))));
    };
    if (X && X.pid === p.id && X.geaendert === E.pruefung.geaendert) zeichne();
    else L.api('GET', '/api/pruefung/' + p.id + '/export').then(x => { X = Object.assign(x, { pid: p.id }); zeichne(); }).catch(e => L.setzen(ort, el('div', { class: 'banner warnung', text: e.message })));
    return ort;
  }

  // --- Reiter Fragen: Einstellungen des Pruefungsmodus und Fragenpool ---
  async function pmAktion(pfad, daten) {
    try { E = await L.api('POST', '/api/pruefung/' + E.pruefung.id + pfad, daten || {}); return E; }
    catch (e) { L.meldung(e.message, true); return null; }
  }

  function einstellungFelder(st) {
    const zahl = (wert, breite) => el('input', { type: 'number', min: 0, value: wert, style: 'width:' + (breite || 90) + 'px' });
    const f = { minuten: zahl(st.minuten), vorwarnung: zahl(st.vorwarnung), gesamt_minuten: zahl(st.gesamt_minuten),
      fragen_anzahl: zahl(st.fragen_anzahl), fragen_gewicht: zahl(st.fragen_gewicht) };
    const inhalt = el('div', { class: 'felder zwei' },
      L.feld('Minuten je Schüler (einzeln)', f.minuten), L.feld('Vorwarnung (Minuten vor Ende)', f.vorwarnung, 'Uhr wird gelb'),
      L.feld('Gesamtzeit (alle parallel)', f.gesamt_minuten, 'Minuten'), L.feld('Fragen je Schüler', f.fragen_anzahl, 'Ziel beim Ziehen'),
      E.pruefung.erfassung === 'bogen' ? L.feld('Gewicht der Fragen in der Note', f.fragen_gewicht, '0 = nur Protokoll; sonst wie ein Bereich des Bogens') : null);
    const werte = () => Object.fromEntries(Object.entries(f).map(([k, i]) => [k, i.value]));
    return { inhalt, werte };
  }

  async function einstellungenDialog(danach) {
    const ef = einstellungFelder(E.pruefung.einstellungen);
    const r = await L.dialog({ titel: 'Einstellungen Prüfungsmodus', inhalt: ef.inhalt,
      speichern: () => L.api('POST', '/api/pruefung/' + E.pruefung.id + '/einstellungen', ef.werte()) });
    if (r) { E = r; if (danach) danach(); }
  }

  function fragenAnsicht() {
    const p = E.pruefung;
    const st = p.einstellungen;
    const viele = el('textarea', { rows: 4, placeholder: 'Eine Frage je Zeile, z. B.\nPneumatik: Was ist ein 5/2-Wegeventil?\nWas macht ein Drosselrückschlagventil?' });
    const einfuegen = async () => { if (await pmAktion('/fragen/einfuegen', { text: viele.value })) { viele.value = ''; detailZeichnen(); } };
    const bearbeiten = async f => {
      const text = el('textarea', { rows: 3, maxlength: 1000 });
      text.value = f.text;
      const kat = el('input', { maxlength: 60, value: f.kategorie, placeholder: 'freiwillig' });
      const r = await L.dialog({ titel: 'Frage', inhalt: el('div', { class: 'felder' }, L.feld('Frage', text), L.feld('Kategorie', kat)),
        weitere: [{ text: 'Löschen', klasse: 'warnen', speichern: () => L.api('POST', '/api/pruefung/' + p.id + '/frage/' + f.id + '/loeschen', {}) }],
        speichern: () => L.api('POST', '/api/pruefung/' + p.id + '/frage/' + f.id, { text: text.value, kategorie: kat.value }) });
      if (r) { E = r; detailZeichnen(); }
    };
    return el('div', { class: 'zwei-spalten' },
      el('div', { class: 'karte stapel' }, el('div', { class: 'zeile' }, el('h3', { text: 'Fragenpool' }), el('span', { class: 'leise klein', text: p.fragen.length + ' Fragen' })),
        p.fragen.length ? el('table', { class: 'liste' }, el('tbody', {}, p.fragen.map(f => el('tr', { class: 'klickbar', onclick: () => bearbeiten(f) },
          el('td', {}, f.kategorie ? el('span', { class: 'chip klein', text: f.kategorie }) : null, ' ', f.text),
          el('td', { class: 'leise klein mono', style: 'white-space:nowrap', text: f.gezogen ? f.gezogen + '× gezogen' : '' })))))
          : el('p', { class: 'leise', text: 'Noch keine Fragen. Im Prüfungsmodus ziehst du je Schüler zufällig Fragen; keine kommt doppelt, solange der Pool reicht.' }),
        viele, el('div', {}, el('button', { type: 'button', onclick: einfuegen }, L.symbol('plus'), 'Fragen hinzufügen'))),
      el('div', { class: 'karte stapel' }, el('h3', { text: 'Prüfungsmodus' }),
        el('div', { class: 'leise klein', text: 'Einzeln: ' + st.minuten + ' min je Schüler, Vorwarnung ' + st.vorwarnung + ' min · Alle parallel: ' + st.gesamt_minuten +
          ' min · ' + st.fragen_anzahl + ' Fragen je Schüler' + (p.erfassung === 'bogen' ? ' · Fragen in der Note: ' + (st.fragen_gewicht ? 'Gewicht ' + fmt(st.fragen_gewicht) : 'nein (nur Protokoll)') : '') }),
        el('div', { class: 'zeile' }, el('button', { type: 'button', onclick: () => einstellungenDialog(detailZeichnen) }, L.symbol('einstellungen'), 'Einstellungen'),
          p.stand !== 'ausgewertet' ? el('button', { type: 'button', class: 'haupt', onclick: pruefungsmodus }, L.symbol('uhr'), 'Prüfungsmodus starten') : null),
        el('p', { class: 'leise klein', text: 'Einschätzung je Frage: ' + p.fragen_stufen.map((s, i) => i + ' = ' + s).join(' · ') })));
  }

  // --- Pruefungsmodus (Vollbild fuers Tablet) ---
  const PM = { modus: 'einzeln', aktiv: null, mitglied: null, start: {}, gesamt: { start: null, verbraucht: 0 }, takt: null, ort: null };

  const mmss = sek => { const a = Math.abs(Math.round(sek)); return (sek < 0 ? '+' : '') + String(Math.floor(a / 60)).padStart(2, '0') + ':' + String(a % 60).padStart(2, '0'); };

  // Eintraege der Liste: Teams (wenn Team-Bereiche) und einzelne Schueler
  function pmEintraege() {
    const p = E.pruefung;
    const aktiv = E.schueler.filter(z => z.aktiv || z.protokoll.length || z.beginn);
    const mitTeams = hatTeams(p) && p.teams.length;
    const liste = [];
    if (mitTeams) p.teams.forEach(t => {
      const m = aktiv.filter(z => z.team_id === t.id);
      if (m.length) liste.push({ id: 't' + t.id, name: t.name, mitglieder: m, team: true });
    });
    aktiv.filter(z => !mitTeams || !z.team_id).forEach(z => liste.push({ id: 's' + z.id, name: z.name, mitglieder: [z], team: false }));
    liste.forEach(e => {
      const z0 = e.mitglieder[0];
      e.zustand = e.mitglieder.every(z => z.fehlt) ? 'fehlt' : z0.ende ? 'fertig' : z0.beginn || PM.start[e.id] ? 'laeuft' : 'offen';
    });
    const rang = { laeuft: 0, offen: 1, fertig: 2, fehlt: 3 };
    return liste.sort((a, b) => rang[a.zustand] - rang[b.zustand] || a.name.localeCompare(b.name, 'de'));
  }

  function pruefungsmodus() {
    if (PM.ort) PM.ort.remove();
    PM.ort = el('div', { class: 'pm', role: 'dialog', 'aria-label': 'Prüfungsmodus' });
    document.body.appendChild(PM.ort);
    document.body.classList.add('pm-offen');
    if (!PM.takt) PM.takt = setInterval(pmUhr, 500);
    pmZeichnen();
  }

  function pmSchliessen() {
    clearInterval(PM.takt); PM.takt = null;
    if (PM.ort) PM.ort.remove();
    PM.ort = null;
    document.body.classList.remove('pm-offen');
    detailZeichnen();
  }

  // Restzeit in Sekunden fuer die Uhr oben
  function pmRest() {
    const st = E.pruefung.einstellungen;
    if (PM.modus === 'parallel') {
      const lauf = PM.gesamt.verbraucht + (PM.gesamt.start ? (Date.now() - PM.gesamt.start) / 1000 : 0);
      return { rest: st.gesamt_minuten * 60 - lauf, laeuft: !!PM.gesamt.start, gesamt: st.gesamt_minuten * 60 };
    }
    const e = PM.aktiv && pmEintraege().find(x => x.id === PM.aktiv);
    if (!e) return { rest: st.minuten * 60, laeuft: false, gesamt: st.minuten * 60 };
    const z0 = e.mitglieder[0];
    let beginn = PM.start[e.id];
    if (!beginn && z0.beginn) beginn = new Date(z0.beginn).getTime();
    const ende = z0.ende ? new Date(z0.ende).getTime() : null;
    if (!beginn) return { rest: st.minuten * 60, laeuft: false, gesamt: st.minuten * 60 };
    return { rest: st.minuten * 60 - ((ende || Date.now()) - beginn) / 1000, laeuft: !ende, gesamt: st.minuten * 60 };
  }

  function pmUhr() {
    if (!PM.ort) return;
    const u = PM.ort.querySelector('.pm-uhr');
    if (!u) return;
    const r = pmRest();
    const vor = E.pruefung.einstellungen.vorwarnung * 60;
    u.textContent = mmss(r.rest);
    u.classList.toggle('gelb', r.rest > 0 && r.rest <= vor);
    u.classList.toggle('rot', r.rest <= 0);
    u.classList.toggle('steht', !r.laeuft);
  }

  function pmZeichnen() {
    if (!PM.ort) return;
    const p = E.pruefung;
    const liste = pmEintraege();
    if (PM.aktiv && !liste.some(e => e.id === PM.aktiv)) PM.aktiv = null;
    const parallelKnoepfe = PM.modus === 'parallel' ? [
      el('button', { type: 'button', class: 'haupt', onclick: () => {
        if (PM.gesamt.start) { PM.gesamt.verbraucht += (Date.now() - PM.gesamt.start) / 1000; PM.gesamt.start = null; } else PM.gesamt.start = Date.now();
        pmZeichnen(); } }, PM.gesamt.start ? '⏸ Pause' : '▶ Start'),
      el('button', { type: 'button', onclick: () => { PM.gesamt = { start: null, verbraucht: 0 }; pmZeichnen(); } }, L.symbol('undo'), 'Zurück')] : [];
    const kopf = el('div', { class: 'pm-kopf' },
      el('div', { class: 'pm-titel' }, el('b', { text: p.titel }), el('span', { class: 'leise klein', text: ERFASSUNG[p.erfassung] })),
      segment([['einzeln', 'Einzeln nacheinander'], ['parallel', 'Alle parallel']], PM.modus, w => { PM.modus = w; pmZeichnen(); }),
      el('div', { class: 'pm-uhr mono', 'aria-live': 'off' }), parallelKnoepfe,
      el('span', { class: 'rechts zeile' },
        el('button', { type: 'button', 'aria-label': 'Einstellungen', onclick: () => einstellungenDialog(pmZeichnen) }, L.symbol('einstellungen')),
        el('button', { type: 'button', onclick: pmSchliessen }, L.symbol('zu'), 'Schließen')));
    const listeEl = el('div', { class: 'pm-liste' }, liste.map(e => el('button', { type: 'button',
      class: 'pm-eintrag ' + e.zustand + (e.id === PM.aktiv ? ' an' : ''), onclick: () => { PM.aktiv = e.id; PM.mitglied = e.mitglieder[0].id; pmZeichnen(); } },
      el('span', { class: 'pm-name' }, e.team ? el('span', { class: 'chip klein team', text: e.name }) : el('b', { text: e.name }),
        e.team ? el('span', { class: 'leise klein', text: ' ' + e.mitglieder.map(z => z.name.split(',')[0]).join(', ') }) : null),
      el('span', { class: 'pm-stand klein' }, e.zustand === 'fertig' && e.mitglieder[0].dauer !== null ? '✓ ' + mmss(e.mitglieder[0].dauer)
        : e.zustand === 'laeuft' ? '● läuft' : e.zustand === 'fehlt' ? 'fehlt' : '',
        e.mitglieder.some(z => z.note) ? el('b', { text: ' ' + e.mitglieder.map(z => z.note ? z.note.text : '–').join(' / ') }) : null))));
    const aktiv = liste.find(e => e.id === PM.aktiv);
    L.setzen(PM.ort, kopf, el('div', { class: 'pm-rumpf' }, listeEl,
      el('div', { class: 'pm-feld' }, aktiv ? pmPanel(aktiv) : el('div', { class: 'leer', text: 'Links einen Schüler bzw. ein Team antippen.' }))));
    pmUhr();
  }

  async function pmLauf(e, aktion) {
    let ok = true;
    for (const z of e.mitglieder) ok = ok && !!(await pmAktion('/lauf/' + z.id, { aktion }));
    if (aktion === 'start') PM.start[e.id] = Date.now();
    else delete PM.start[e.id];
    if (ok && aktion === 'ende') {   // naechster offener wird vorgeschlagen, aber nicht gestartet
      const naechster = pmEintraege().find(x => x.zustand === 'offen');
      PM.aktiv = naechster ? naechster.id : e.id;
      PM.mitglied = naechster ? naechster.mitglieder[0].id : PM.mitglied;
    }
    pmZeichnen();
  }

  function pmPanel(e) {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    if (!e.mitglieder.some(z => z.id === PM.mitglied)) PM.mitglied = e.mitglieder[0].id;
    const z = E.schueler.find(x => x.id === PM.mitglied);
    const z0 = e.mitglieder[0];
    const laeuft = (z0.beginn || PM.start[e.id]) && !z0.ende;
    const steuerung = PM.modus === 'einzeln' ? el('div', { class: 'zeile pm-steuer' },
      !laeuft && !z0.ende ? el('button', { type: 'button', class: 'haupt gross', onclick: () => pmLauf(e, 'start') }, '▶ Start') : null,
      laeuft ? el('button', { type: 'button', class: 'haupt gross', onclick: () => pmLauf(e, 'ende') }, L.symbol('ok'), 'Fertig') : null,
      z0.ende ? el('span', { class: 'chip gruen', text: 'fertig nach ' + mmss(z0.dauer || 0) }) : null,
      z0.beginn || z0.ende ? el('button', { type: 'button', class: 'leicht klein', onclick: () => pmLauf(e, 'zuruecksetzen') }, L.symbol('undo'), 'Zeit zurücksetzen') : null) : null;
    const mitglieder = e.mitglieder.length > 1 ? el('div', { class: 'segment', role: 'group', 'aria-label': 'Wer wird bewertet' }, e.mitglieder.map(m =>
      el('button', { type: 'button', class: m.id === z.id ? 'an' : null, onclick: () => { PM.mitglied = m.id; pmZeichnen(); } }, m.name.split(',')[0]))) : null;
    // Fragen: ziehen, spontan notieren, Einschaetzung je Frage
    const st = p.einstellungen;
    const spontan = el('input', { maxlength: 1000, placeholder: 'Spontane Frage notieren …', 'aria-label': 'Spontane Frage' });
    const notieren = async () => { if (spontan.value.trim() && await pmAktion('/protokoll', { schueler_id: z.id, text: spontan.value })) pmZeichnen(); };
    spontan.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); notieren(); } });
    const fragenEl = el('section', { class: 'ov-ab' },
      el('div', { class: 'ab-kopf' }, el('span', { text: 'Fragen' }), el('span', { class: 'leise klein', text: z.protokoll.filter(x => !x.spontan).length + ' von ' + st.fragen_anzahl + ' gezogen' }),
        el('span', { class: 'rechts' }, !fertig ? el('button', { type: 'button', class: 'klein', disabled: !p.fragen.length ? true : null,
          title: p.fragen.length ? null : 'Fragenpool ist leer (Reiter „Fragen“)', onclick: async () => { if (await pmAktion('/ziehen/' + z.id)) pmZeichnen(); } }, '🎲 Frage ziehen') : null)),
      el('div', { class: 'ab-inhalt' },
        z.protokoll.map(x => el('div', { class: 'pm-frage' },
          el('div', { class: 'zeile' }, x.spontan ? el('span', { class: 'chip klein', text: 'spontan' }) : null, el('b', { class: 'pm-frage-text', text: x.text }),
            !fertig ? el('span', { class: 'rechts zeile' },
              x.spontan ? el('button', { type: 'button', class: 'leicht klein', title: 'In den Fragenpool übernehmen', onclick: async () => { if (await pmAktion('/protokoll/' + x.id, { in_pool: true })) { L.meldung('In den Pool übernommen.'); pmZeichnen(); } } }, L.symbol('plus'), 'Pool') : null,
              el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Eintrag entfernen', onclick: async () => { if (await pmAktion('/protokoll/' + x.id + '/loeschen')) pmZeichnen(); } }, L.symbol('zu'))) : null),
          el('div', { class: 'stufen-wahl pm-skala', role: 'group', 'aria-label': 'Einschätzung' }, p.fragen_stufen.map((name, i) =>
            el('button', { type: 'button', class: x.stufe === i ? 'an' : null, disabled: fertig ? true : null,
              onclick: async () => { if (await pmAktion('/protokoll/' + x.id, { stufe: x.stufe === i ? null : i })) pmZeichnen(); } },
            el('b', { text: String(i) }), el('span', { class: 'leise', text: name })))))),
        !fertig ? el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, spontan, el('button', { type: 'button', onclick: notieren }, 'notieren')) : null));
    return el('div', { class: 'stapel', style: 'gap:10px' },
      el('div', { class: 'zeile' }, el('h2', { text: e.team ? e.name : z.name }), mitglieder, z.note ? el('span', { class: 'chip blau', text: z.note.text + ' · ' + fmt(z.prozent) + ' %' }) : null),
      steuerung, fragenEl, pmBewertung(z));
  }

  // Bewertung des gewaehlten Schuelers: Bogen bzw. Checkliste bzw. Punkte, grosse Felder
  function pmBewertung(z) {
    const p = E.pruefung;
    const fertig = p.stand === 'ausgewertet';
    const setze = async (key, wert) => { if (await speichern(z.id, { werte: { [key]: wert } })) pmZeichnen(); };
    if (p.erfassung === 'gesamt') {
      return el('section', { class: 'ov-ab' }, el('div', { class: 'ab-kopf', text: 'Bewertung' }), el('div', { class: 'ab-inhalt' },
        el('div', { class: 'zeile' }, el('input', { inputmode: 'decimal', class: 'punkte gross', value: z.werte.gesamt === undefined ? '' : fmt(z.werte.gesamt, 2), disabled: fertig ? true : null,
          onchange: ev => setze('gesamt', ev.target.value.replace(',', '.')) }), el('span', { class: 'leise', text: 'von ' + fmt(p.max_punkte) + ' P' }))));
    }
    return el('div', { class: 'stapel', style: 'gap:10px' }, p.struktur.bereiche.map(b => el('section', { class: 'ov-ab' },
      el('div', { class: 'ab-kopf' }, el('span', { text: b.name }), b.team && z.team ? el('span', { class: 'chip klein team', text: 'gilt für ' + z.team }) : null),
      el('div', { class: 'ab-inhalt' }, b.kriterien.map(k => {
        const wert = z.werte[k.key];
        let eingabe;
        if (k.typ === 'stufen') {
          eingabe = el('div', { class: 'stufen-wahl', role: 'group', 'aria-label': k.name }, k.stufen.map((s, i) => el('button', { type: 'button', class: wert === i ? 'an' : null,
            disabled: fertig ? true : null, title: s.text || null, onclick: () => setze(k.key, wert === i ? null : i) }, el('b', { text: s.name }), el('span', { class: 'leise', text: fmt(s.punkte) + ' P' }))));
        } else if (k.typ === 'punkte') {
          eingabe = el('div', { class: 'zeile' }, el('input', { inputmode: 'decimal', class: 'punkte gross', value: wert === undefined ? '' : fmt(wert, 2), disabled: fertig ? true : null,
            onchange: ev => setze(k.key, ev.target.value.replace(',', '.')) }), el('span', { class: 'leise', text: 'von ' + fmt(k.max) + ' P' }));
        } else if (k.typ === 'check' || k.typ === 'haken') {
          eingabe = el('label', { class: 'haken gross' }, el('input', { type: 'checkbox', checked: wert ? true : null, disabled: fertig ? true : null,
            onchange: ev => setze(k.key, ev.target.checked ? true : null) }), el('span', { text: k.typ === 'check' ? fmt(k.max) + ' P' : 'erledigt' }));
        } else {
          const t = el('textarea', { rows: 2, disabled: fertig ? true : null, onchange: ev => setze(k.key, ev.target.value) });
          t.value = wert || '';
          eingabe = t;
        }
        return el('div', { class: 'kriterium' }, el('b', { text: k.name }), eingabe);
      })))),
      el('section', { class: 'ov-ab' }, el('div', { class: 'ab-kopf', text: 'Notiz' }), el('div', { class: 'ab-inhalt' }, (() => {
        const t = el('textarea', { rows: 2, disabled: fertig ? true : null, placeholder: 'Gesamteindruck, Begründung …', onchange: ev => speichern(z.id, { notiz: ev.target.value }) });
        t.value = z.notiz || '';
        return t;
      })())));
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
    const teamText = b => {
      if (!b.team || !z.team_id) return null;
      const t = p.teams.find(x => x.id === z.team_id);
      return el('span', { class: 'chip klein team', title: 'Gilt für alle im Team', text: 'Team ' + (t ? t.name + ': ' + t.mitglieder.length + ' Schüler' : '') });
    };
    const bereiche = p.struktur.bereiche.map(b => el('section', { class: 'ov-ab' },
      el('div', { class: 'ab-kopf' }, el('span', { text: b.name }), teamText(b), el('span', { class: 'leise klein', text: 'Gewicht ' + fmt(b.gewicht) })),
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
        } else if (k.typ === 'check') {
          eingabe = el('label', { class: 'haken' }, el('input', { type: 'checkbox', checked: wert ? true : null, disabled: fertig ? true : null,
            onchange: ev => setze(k.key, ev.target.checked ? true : null) }), fmt(k.max) + ' P');
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
    if (E.pruefung.erfassung === 'checkliste') {
      const n = E.schueler.filter(z => z.aktiv && !z.fehlt).length || 1;
      const fortschritt = el('div', { class: 'karte stapel' }, el('h3', { text: 'Fortschritt je Versuch' }),
        el('table', { class: 'liste' }, el('tbody', {}, E.pruefung.struktur.bereiche.map((v, i) => el('tr', {},
          el('td', { text: v.name + (v.team ? ' (Team)' : '') }),
          el('td', { style: 'width:45%' }, el('div', { class: 'anteil' }, el('span', { style: 'width:' + Math.round(100 * st.fortschritt[i] / n) + '%' }))),
          el('td', { class: 'mono zahl', text: st.fortschritt[i] + ' / ' + n }))))));
      if (E.pruefung.struktur.testat) return fortschritt;
      const rest = auswertungNoten();
      rest.appendChild(fortschritt);
      return rest;
    }
    return auswertungNoten();
  }

  function auswertungNoten() {
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
