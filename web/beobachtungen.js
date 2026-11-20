// Beobachtungen je Schueler (0.26.0), immer privat je Lehrkraft. Verlauf eines Schuelers (#klassen-schueler-<id>),
// Klassenuebersicht mit Filtern (#klassen-beobachtungen), Abschnitt im Stunden-Fenster (mehrere Schueler auf einmal),
// Hinweis auf der Startseite zum Aufraeumen alter Eintraege zu Schuelern, die nicht mehr in der Klasse sind.
'use strict';

const Beobachtungen = (() => {
  const el = L.el;
  const KATEGORIEN = ['Leistung', 'Arbeitsverhalten', 'Sozialverhalten', 'Sonstiges'];
  const KAT_FARBE = { Leistung: 'blau', Arbeitsverhalten: 'gelb', Sozialverhalten: 'lila', Sonstiges: '' };
  const TENDENZ = { positiv: ['+ positiv', 'gruen', '+'], neutral: ['○ neutral', '', '○'], negativ: ['− negativ', 'rot', '−'] };
  const PRIVAT = 'Nur für dich sichtbar – Beobachtungen werden nie im Kollegium geteilt.';
  const zustand = { klasse: null, filter: { kategorie: '', tendenz: '', von: '', bis: '', suche: '' }, verlaufFilter: '' };

  const chips = e => [e.kategorie ? el('span', { class: 'chip ' + (KAT_FARBE[e.kategorie] || ''), text: e.kategorie }) : null,
    el('span', { class: 'chip ' + TENDENZ[e.tendenz][1], text: TENDENZ[e.tendenz][0] })];
  // Zaehler "+2 ○1 −0" fuer Listen
  const zaehler = z => el('span', { class: 'tend' }, el('span', { class: 'p', text: '+' + z.positiv }),
    el('span', { class: 'n', text: '○' + z.neutral }), el('span', { class: 'm', text: '−' + z.negativ }));
  const kategorieWahl = (wert, leer = '– keine –') => el('select', { 'aria-label': 'Kategorie' }, el('option', { value: '', text: leer }),
    KATEGORIEN.map(k => el('option', { value: k, text: k, selected: k === wert ? true : null })));

  // Segment +/○/−; liefert { teil, wert() }
  function tendenzWahl(start = 'neutral') {
    let wert = start;
    const knoepfe = Object.entries(TENDENZ).map(([w, [text]]) => el('button', { type: 'button', class: w === wert ? 'an' : null,
      'aria-pressed': w === wert ? 'true' : 'false', onclick: () => {
        wert = w;
        knoepfe.forEach(k => { const an = k.dataset.w === w; k.classList.toggle('an', an); k.setAttribute('aria-pressed', an ? 'true' : 'false'); });
      } }, text));
    knoepfe.forEach((k, i) => { k.dataset.w = Object.keys(TENDENZ)[i]; });
    return { teil: el('div', { class: 'segment', role: 'group', 'aria-label': 'Tendenz' }, knoepfe), wert: () => wert };
  }

  // Eintrag aendern bzw. loeschen (Dialog); Rueckgabe true bei Aenderung
  async function bearbeiten(e) {
    const datum = el('input', { type: 'date', value: e.datum });
    const kat = kategorieWahl(e.kategorie);
    const tend = tendenzWahl(e.tendenz);
    const text = el('textarea', { rows: 4, maxlength: 4000 });
    text.value = e.text;
    const r = await L.dialog({
      titel: 'Beobachtung', weitere: [{ text: 'Löschen', klasse: 'warnen', speichern: () => L.api('POST', '/api/beobachtung/' + e.id + '/loeschen', {}) }],
      inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Datum', datum), L.feld('Kategorie', kat)),
        el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'leise klein', style: 'font-weight:600', text: 'Tendenz' }), tend.teil),
        L.feld('Beobachtung', text),
        e.stunde_datum ? el('p', { class: 'leise klein', text: 'Notiert in der Stunde ' + L.tag(e.stunde_datum) + (e.stunde_text ? ' · ' + e.stunde_text : '') }) : null),
      speichern: () => L.api('POST', '/api/beobachtung/' + e.id, { datum: datum.value, kategorie: kat.value, tendenz: tend.wert(), text: text.value }),
    });
    return !!r;
  }

  function eintragZeile(e, nachher, mitName) {
    return el('article', { class: 'bo-eintrag' },
      el('div', { class: 'zeile' }, el('span', { class: 'mono', text: L.tag(e.datum, true) }), mitName || null, chips(e),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht klein', onclick: async () => { if (await bearbeiten(e)) nachher(); } },
          L.symbol('stift'), 'Bearbeiten'))),
      el('p', { class: 'bo-text', text: e.text }),
      e.stunde_datum ? el('span', { class: 'bo-quelle' }, L.symbol('kalender'), 'aus der Stunde ' + L.tag(e.stunde_datum) + (e.stunde_text ? ' · ' + e.stunde_text : '')) : null);
  }

  // --- Verlauf eines Schuelers ---

  async function verlaufZeigen(ort, sid) {
    const V = await L.api('GET', '/api/beobachtungen?schueler=' + sid);
    const s = V.schueler;
    zustand.klasse = s.klasse_id;
    L.titel(s.name);
    const neu = () => verlaufZeigen(ort, sid);
    const datum = el('input', { type: 'date', value: L.heute() });
    const kat = kategorieWahl('');
    const tend = tendenzWahl('neutral');
    const text = el('textarea', { rows: 5, maxlength: 4000, placeholder: 'Was ist dir aufgefallen?' });
    const notieren = async () => {
      try {
        await L.api('POST', '/api/beobachtung', { schueler_ids: [sid], datum: datum.value, kategorie: kat.value, tendenz: tend.wert(), text: text.value });
        L.meldung('Notiert.');
        neu();
      } catch (e) { L.meldung(e.message, true); }
    };
    const anzahl = k => V.eintraege.filter(e => !k || e.kategorie === k).length;
    const filter = el('div', { class: 'segment', role: 'group', 'aria-label': 'Kategorie filtern' },
      [''].concat(KATEGORIEN).map(k => el('button', { type: 'button', class: zustand.verlaufFilter === k ? 'an' : null,
        onclick: () => { zustand.verlaufFilter = k; neu(); } }, (k || 'Alle') + ' (' + anzahl(k) + ')')));
    const sichtbar = V.eintraege.filter(e => !zustand.verlaufFilter || e.kategorie === zustand.verlaufFilter);
    L.setzen(ort,
      el('div', { class: 'werkzeug' },
        el('a', { class: 'knopf klein', href: '#klassen' }, L.symbol('links'), 'Schülerliste'),
        Fotos.avatar(s, 40), el('h1', { class: 'dreieck', text: s.name }), el('span', { class: 'chip blau', text: s.klasse }),
        s.aktiv ? null : el('span', { class: 'chip', text: 'nicht mehr in der Klasse' }),
        s.entlassen_zum ? el('span', { class: 'chip gelb', text: 'ausgeschult · letzter Tag ' + L.tag(s.entlassen_zum, true) }) : null,
        el('span', { class: 'rechts zeile' },
          s.aktiv && !s.entlassen_zum ? el('button', { type: 'button', onclick: () => Formulare.entlassung(sid, neu) }, L.symbol('abmelden'), 'Ausschulung …') : null,
          el('button', { type: 'button', onclick: () => Pruefungen.schuelerBearbeiten(sid, neu) }, L.symbol('stift'), 'Stammdaten …'),
          V.eintraege.length ? el('button', { type: 'button', onclick: () => L.ansehen('/api/beobachtungen/schueler/' + sid + '.pdf').catch(e => L.meldung(e.message, true)) },
            L.symbol('formular'), 'PDF') : null)),
      el('div', { class: 'bo-spalten' },
        el('section', { class: 'karte stapel', style: 'gap:12px' }, el('h2', { class: 'dreieck', text: 'Neue Beobachtung' }),
          el('div', { class: 'felder' }, L.feld('Datum', datum), L.feld('Kategorie (freiwillig)', kat),
            el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'leise klein', style: 'font-weight:600', text: 'Tendenz' }), tend.teil),
            L.feld('Beobachtung', text),
            el('div', {}, el('button', { type: 'button', class: 'haupt', onclick: notieren }, L.symbol('plus'), 'Notieren')),
            el('p', { class: 'banner klein' }, L.symbol('schloss'), ' ' + PRIVAT))),
        el('section', { class: 'karte stapel', style: 'gap:8px' },
          el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Verlauf' }), el('span', { class: 'chip', text: String(V.eintraege.length) }),
            el('span', { class: 'rechts leise klein', text: 'neueste oben' })),
          V.eintraege.length ? filter : null,
          sichtbar.length ? el('div', {}, sichtbar.map(e => eintragZeile(e, neu)))
            : el('p', { class: 'leise', style: 'padding:12px 0', text: V.eintraege.length ? 'Keine Beobachtungen in dieser Kategorie.' : 'Noch keine Beobachtungen.' }))));
  }

  // --- Klassenuebersicht ---

  async function uebersichtZeigen(ort) {
    const K = (await L.api('GET', '/api/schueler/klassen')).klassen;
    if (!K.length) return L.setzen(ort, el('div', { class: 'leer', text: 'Du hast noch keine Klassen.' }));
    if (!zustand.klasse || !K.some(k => k.id === zustand.klasse)) zustand.klasse = (K.find(k => k.meine) || K[0]).id;
    const f = zustand.filter;
    const q = ['klasse=' + zustand.klasse].concat(Object.entries(f).filter(([, w]) => w).map(([k, w]) => k + '=' + encodeURIComponent(w))).join('&');
    const B = await L.api('GET', '/api/beobachtungen?' + q);
    const neu = () => uebersichtZeigen(ort);
    const auswahl = el('select', { 'aria-label': 'Klasse', style: 'width:auto', onchange: () => { zustand.klasse = Number(auswahl.value); neu(); } },
      K.map(k => el('option', { value: k.id, text: k.name, selected: k.id === zustand.klasse ? true : null })));
    const segment = (werte, aktuell, setze) => el('div', { class: 'segment', role: 'group' }, werte.map(([w, t]) =>
      el('button', { type: 'button', class: aktuell === w ? 'an' : null, onclick: () => { setze(w); neu(); } }, t)));
    const suche = el('input', { type: 'search', value: f.suche, placeholder: 'Name oder Text', 'aria-label': 'Suche' });
    suche.addEventListener('change', () => { f.suche = suche.value.trim(); neu(); });
    const von = el('input', { type: 'date', value: f.von, 'aria-label': 'von' });
    const bis = el('input', { type: 'date', value: f.bis, 'aria-label': 'bis' });
    von.addEventListener('change', () => { f.von = von.value; neu(); });
    bis.addEventListener('change', () => { f.bis = bis.value; neu(); });
    const je = {};
    B.eintraege.forEach(e => { (je[e.schueler_id] = je[e.schueler_id] || []).push(e); });
    const mit = B.schueler.filter(s => je[s.id]);
    const n = { positiv: 0, neutral: 0, negativ: 0 };
    B.eintraege.forEach(e => { n[e.tendenz] += 1; });
    L.setzen(ort,
      el('div', { class: 'zeile' }, auswahl, el('span', { class: 'leise klein', text: B.eintraege.length + ' Beobachtungen · ' + mit.length + ' Schüler · ' + PRIVAT }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', disabled: B.eintraege.length ? null : true,
          onclick: () => L.ansehen('/api/beobachtungen/klasse.pdf?' + q).catch(e => L.meldung(e.message, true)) }, L.symbol('formular'), 'PDF der Klasse'))),
      el('section', { class: 'karte bo-filter', 'aria-label': 'Filter' },
        el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'Kategorie' }),
          segment([['', 'Alle']].concat(KATEGORIEN.map(k => [k, k])), f.kategorie, w => { f.kategorie = w; })),
        el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'Tendenz' }),
          segment([['', 'Alle'], ['positiv', '+'], ['neutral', '○'], ['negativ', '−']], f.tendenz, w => { f.tendenz = w; })),
        el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'Zeitraum' }), el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, von, bis)),
        el('label', { class: 'stapel', style: 'gap:4px;flex:1 1 180px' }, el('span', { class: 'etikett', text: 'Suche' }), suche),
        Object.values(f).some(Boolean) ? el('button', { type: 'button', class: 'leicht klein', onclick: () => { Object.keys(f).forEach(k => { f[k] = ''; }); neu(); } }, 'Filter zurücksetzen') : null),
      mit.length ? el('div', { class: 'stapel', style: 'gap:12px' }, mit.map(s => el('section', { class: 'karte stapel', style: 'gap:2px' },
        el('div', { class: 'zeile bo-kopf' }, el('a', { href: '#klassen-schueler-' + s.id, class: 'bo-name' }, Fotos.mitName(s, 34)),
          el('span', { class: 'chip', text: je[s.id].length + (je[s.id].length === 1 ? ' Eintrag' : ' Einträge') }),
          zaehler({ positiv: je[s.id].filter(e => e.tendenz === 'positiv').length, neutral: je[s.id].filter(e => e.tendenz === 'neutral').length,
            negativ: je[s.id].filter(e => e.tendenz === 'negativ').length }),
          el('span', { class: 'rechts' }, el('a', { class: 'knopf klein', href: '#klassen-schueler-' + s.id }, 'Verlauf'))),
        je[s.id].map(e => eintragZeile(e, neu)))))
        : el('div', { class: 'leer', text: Object.values(f).some(Boolean) ? 'Keine Beobachtungen passen zum Filter.' : 'In dieser Klasse hast du noch keine Beobachtungen. Notiere sie beim Schüler (Klick in der Schülerliste) oder im Stunden-Fenster.' }));
  }

  // --- Abschnitt im Stunden-Fenster: Schueler antippen (auch mehrere), Kategorie, Tendenz, Text ---

  function stundeAbschnitt(S) {
    const ort = el('div', { class: 'stapel', style: 'gap:10px' }, el('p', { class: 'leise klein', text: 'Lädt …' }));
    const zahl = el('span', { class: 'chip klein', text: '…' });
    const stundeText = (S.zeile && S.zeile.bezeichnung ? S.zeile.bezeichnung : S.beginn) + (S.thema ? ' · ' + S.thema.titel : '');
    const gewaehlt = new Set();
    let entwurf = { kat: '', tend: 'neutral', text: '' };
    async function laden() {
      let L1, E;
      try {
        [L1, E] = await Promise.all([L.api('GET', '/api/schueler?klasse=' + S.klasse.id), L.api('GET', '/api/beobachtungen/stunde?datum=' + S.datum + '&beginn=' + encodeURIComponent(S.beginn))]);
      } catch (e) { L.setzen(ort, el('p', { class: 'leise klein', text: e.message })); return; }
      zahl.textContent = String(E.eintraege.length);
      let liste = L1.schueler.filter(s => s.aktiv);
      if (S.gruppe && liste.some(s => s.gruppe_id === S.gruppe.id)) liste = liste.filter(s => s.gruppe_id === S.gruppe.id);   // nur meine Gruppe
      if (!liste.length) {
        L.setzen(ort, el('p', { class: 'leise klein' }, 'Für diese Klasse gibt es noch keine Schülerliste. ', el('a', { href: '#klassen', text: 'Zur Schülerliste' })));
        return;
      }
      const kat = kategorieWahl(entwurf.kat, 'Kategorie: keine');
      const tend = tendenzWahl(entwurf.tend);
      const text = el('input', { maxlength: 4000, placeholder: 'Was ist dir aufgefallen?', value: entwurf.text, 'aria-label': 'Beobachtung' });
      const hinweis = el('span', { class: 'leise klein' });
      const hinweisSetzen = () => { hinweis.textContent = gewaehlt.size ? 'Wird bei ' + (gewaehlt.size === 1 ? liste.find(s => gewaehlt.has(s.id)).name : gewaehlt.size + ' Schülern') + ' im Verlauf eingetragen.' : 'Erst Schüler antippen (auch mehrere).'; };
      const knoepfe = liste.map(s => {
        const k = el('button', { type: 'button', class: 'bo-wahl' + (gewaehlt.has(s.id) ? ' an' : ''), 'aria-pressed': gewaehlt.has(s.id) ? 'true' : 'false', onclick: () => {
          if (gewaehlt.has(s.id)) gewaehlt.delete(s.id); else gewaehlt.add(s.id);
          k.classList.toggle('an', gewaehlt.has(s.id));
          k.setAttribute('aria-pressed', gewaehlt.has(s.id) ? 'true' : 'false');
          hinweisSetzen();
        } }, Fotos.avatar(s, 24), s.name);
        return k;
      });
      const notieren = async () => {
        entwurf = { kat: kat.value, tend: tend.wert(), text: text.value };
        try {
          await L.api('POST', '/api/beobachtung', { schueler_ids: [...gewaehlt], datum: S.datum, kategorie: kat.value, tendenz: tend.wert(), text: text.value,
            stunde_datum: S.datum, stunde_beginn: S.beginn, stunde_text: stundeText });
          gewaehlt.clear();
          entwurf = { kat: '', tend: 'neutral', text: '' };
          L.meldung('Notiert.');
          laden();
        } catch (e) { L.meldung(e.message, true); }
      };
      text.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); notieren(); } });
      hinweisSetzen();
      L.setzen(ort,
        el('div', { class: 'bo-wahlen', role: 'group', 'aria-label': 'Schüler' }, knoepfe),
        el('div', { class: 'bo-eingabe' }, kat, tend.teil, text),
        el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'haupt klein', onclick: notieren }, L.symbol('plus'), 'Notieren'), hinweis),
        E.eintraege.length ? el('div', { class: 'stapel', style: 'gap:0' }, el('span', { class: 'etikett', text: 'In dieser Stunde notiert' }),
          E.eintraege.map(e => eintragZeile(e, laden, el('a', { href: '#klassen-schueler-' + e.schueler_id, class: 'bo-name', text: e.name })))) : null);
    }
    laden();
    return el('section', { class: 'ov-ab' },
      el('div', { class: 'ab-kopf' }, L.symbol('auge'), el('span', { text: 'Beobachtungen zu Schülern' }), zahl,
        el('span', { class: 'rechts leise', style: 'font-weight:400', text: 'nur für dich' })),
      el('div', { class: 'ab-inhalt' }, ort));
  }

  // --- Startseite: alte Beobachtungen zu Schuelern, die nicht mehr in der Klasse sind ---

  async function aufraeumenHinweis() {
    let A;
    try { A = await L.api('GET', '/api/beobachtungen/aufraeumen'); } catch (e) { return null; }
    if (!A.anzahl) return null;
    const karte = el('div', { class: 'banner', style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap' },
      L.symbol('muell'), el('span', { text: A.anzahl + (A.anzahl === 1 ? ' Beobachtung' : ' Beobachtungen') + ' zu Schülern, die nicht mehr in der Klasse sind, ist älter als ein Jahr.' }),
      el('button', { type: 'button', class: 'klein', onclick: async () => {
        const r = await L.dialog({ titel: 'Alte Beobachtungen löschen?', knopf: 'Löschen', gefaehrlich: true,
          inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, el('p', { text: 'Gelöscht werden nur deine eigenen Beobachtungen vor dem ' + L.tag(A.grenze, true) + ' zu:' }),
            el('ul', {}, A.schueler.map(s => el('li', { text: s.name + ' (' + s.klasse + ') · ' + s.anzahl })))),
          speichern: () => L.api('POST', '/api/beobachtungen/aufraeumen', {}) });
        if (r) { L.meldung(r.geloescht + ' gelöscht.'); karte.remove(); }
      } }, 'Ansehen und löschen …'));
    return karte;
  }

  return { verlaufZeigen, uebersichtZeigen, stundeAbschnitt, aufraeumenHinweis, zaehler, zustand };
})();
