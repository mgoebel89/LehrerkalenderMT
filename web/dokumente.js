'use strict';
// Dokumente (Stufe F3): das eigene Paperless-ngx je Konto, aus dem alten drs-lxc uebernommen. Der Browser kennt weder
// Adresse noch Token, alles laeuft ueber /api/dokumente/... Liste mit Suche und Tag-Filter (nur Dokumente mit einem der
// Anzeige-Tags), Detail mit Metadaten und Notizen, Hochladen mit Upload-Tag und Speicherpfad aus den Einstellungen.
// Die Vorschau oeffnet in einem eigenen Tab (die Seite laesst sich nicht in Rahmen einbetten).
const Dokumente = (() => {
  const el = L.el;
  let ort = null;
  let ST = null;                                   // Stammlisten: tags, pfade, korrespondenten, typen, anzeige_tags, ...
  const zustand = { suche: '', tags: [], sortierung: '-created', seite: 1, liste: [], weiter: false, anzahl: 0 };
  let folge = 0;                                   // schnelles Tippen: nur die neueste Antwort zeichnen

  const datumText = iso => iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '';
  const nachId = (liste, id) => (liste || []).find(x => x.id === id);
  function tagFarbe(hex) {
    const h = (hex || '').trim();
    return /^#?[0-9a-f]{6}$/i.test(h) ? (h[0] === '#' ? h : '#' + h) : '#e8eef4';
  }
  function schrift(hex) {
    const h = tagFarbe(hex).slice(1);
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#111' : '#fff';
  }
  const tagChip = t => el('span', { class: 'dok-tag', style: 'background:' + tagFarbe(t.color) + ';color:' + schrift(t.color), text: t.name });
  const tagsVon = d => el('span', { class: 'dok-tags' }, (d.tags || []).map(id => nachId(ST && ST.tags, id)).filter(Boolean).map(tagChip));

  // Tags als Umschalter (Mehrfachwahl); liefert { knoten, wert() }
  function tagWahl(liste, gewaehlt) {
    let wahl = (gewaehlt || []).slice();
    const knoten = el('div', { class: 'dok-chips' });
    const zeichnen = () => L.setzen(knoten, (liste || []).map(t => el('button', {
      type: 'button', class: 'dok-chip' + (wahl.includes(t.id) ? ' an' : ''), 'aria-pressed': wahl.includes(t.id) ? 'true' : 'false',
      onclick: () => { wahl = wahl.includes(t.id) ? wahl.filter(x => x !== t.id) : wahl.concat([t.id]); zeichnen(); } }, t.name)));
    zeichnen();
    return { knoten, wert: () => wahl.slice() };
  }

  function auswahl(liste, wert, leer) {
    const s = el('select', {}, el('option', { value: '', text: leer || '– keine –' }),
      (liste || []).map(x => el('option', { value: x.id, text: x.name })));
    s.value = wert ? String(wert) : '';
    return s;
  }

  // --- Bereich "Dokumente" ---

  async function zeigen(ortEl) {
    ort = ortEl;
    const k = await L.api('GET', '/api/dokumente/konfig');
    if (!k.verbunden) {
      L.setzen(ort, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Dokumente' })),
        el('div', { class: 'banner warnung' }, k.fehler || 'Paperless ist nicht verbunden. ', el('a', { href: '#einstellungen-konto', text: 'Unter Einstellungen › Konto verbinden' })));
      return;
    }
    L.setzen(ort, el('p', { class: 'leise', text: 'Verbindet mit Paperless …' }));
    try { ST = await L.api('GET', '/api/dokumente/stammlisten'); } catch (e) {
      L.setzen(ort, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Dokumente' })), el('div', { class: 'banner warnung', text: e.message }),
        el('div', {}, el('button', { type: 'button', onclick: () => zeigen(ort) }, L.symbol('refresh'), 'Noch einmal')));
      return;
    }
    gerueste();
    neuLaden();
  }

  let ergebnisOrt = null, mehrKnopf = null, zahlOrt = null;
  function gerueste() {
    const suche = el('input', { type: 'search', placeholder: 'Titel und Inhalt durchsuchen …', value: zustand.suche, 'aria-label': 'Suche' });
    let timer = null;
    suche.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { zustand.suche = suche.value.trim(); neuLaden(); }, 350); });
    const sortierung = el('select', { 'aria-label': 'Sortierung', onchange: ev => { zustand.sortierung = ev.target.value; neuLaden(); } },
      [['-created', 'Neueste zuerst'], ['created', 'Älteste zuerst'], ['title', 'Titel A–Z'], ['-added', 'Zuletzt hinzugefügt']]
        .map(([w, t]) => el('option', { value: w, text: t, selected: zustand.sortierung === w ? true : null })));
    const filterTags = ST.anzeige_tags.length ? ST.tags.filter(t => ST.anzeige_tags.includes(t.id)) : ST.tags;
    const filter = el('div', { class: 'dok-chips' });
    const filterZeichnen = () => L.setzen(filter, filterTags.map(t => el('button', {
      type: 'button', class: 'dok-chip' + (zustand.tags.includes(t.id) ? ' an' : ''),
      onclick: () => { zustand.tags = zustand.tags.includes(t.id) ? zustand.tags.filter(x => x !== t.id) : zustand.tags.concat([t.id]); filterZeichnen(); neuLaden(); } },
    t.name)));
    filterZeichnen();
    ergebnisOrt = el('div', { class: 'dok-raster' });
    mehrKnopf = el('button', { type: 'button', hidden: true, onclick: () => { zustand.seite += 1; laden(true); } }, 'Mehr laden');
    zahlOrt = el('span', { class: 'leise klein' });
    L.setzen(ort,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Dokumente' }), zahlOrt,
        el('button', { type: 'button', class: 'haupt', onclick: hochladen }, L.symbol('hoch'), 'Hochladen')),
      el('div', { class: 'zeile dok-filter' }, suche, sortierung,
        el('button', { type: 'button', class: 'leicht', title: 'Neu laden', 'aria-label': 'Neu laden', onclick: neuLaden }, L.symbol('refresh'))),
      filterTags.length ? filter : null,
      ergebnisOrt, el('div', { style: 'text-align:center' }, mehrKnopf));
  }

  function neuLaden() { zustand.seite = 1; laden(false); }

  async function laden(anhaengen) {
    const meine = ++folge;
    if (!anhaengen) L.setzen(ergebnisOrt, el('p', { class: 'leise', text: 'Lädt …' }));
    const p = new URLSearchParams({ suche: zustand.suche, tags: zustand.tags.join(','), sortierung: zustand.sortierung, seite: String(zustand.seite) });
    let d;
    try { d = await L.api('GET', '/api/dokumente?' + p); } catch (e) {
      if (meine === folge) L.setzen(ergebnisOrt, el('div', { class: 'banner warnung', text: e.message }));
      return;
    }
    if (meine !== folge || !ergebnisOrt.isConnected) return;
    zustand.liste = anhaengen ? zustand.liste.concat(d.dokumente) : d.dokumente;
    zustand.weiter = d.weiter;
    zahlOrt.textContent = d.anzahl + (d.anzahl === 1 ? ' Dokument' : ' Dokumente');
    mehrKnopf.hidden = !d.weiter;
    L.setzen(ergebnisOrt, zustand.liste.length ? zustand.liste.map(kachel)
      : el('div', { class: 'leer', text: zustand.suche || zustand.tags.length ? 'Nichts gefunden.' : 'Noch keine Dokumente mit deinen Anzeige-Tags.' }));
  }

  function kachel(d) {
    const bild = el('img', { src: '/api/dokumente/' + d.id + '/thumb', alt: '', loading: 'lazy' });
    bild.addEventListener('error', () => bild.replaceWith(L.symbol('formular')));
    const k = nachId(ST.korrespondenten, d.korrespondent);
    return el('button', { type: 'button', class: 'dok-kachel', onclick: () => detail(d.id) },
      el('span', { class: 'dok-bild' }, bild),
      el('span', { class: 'dok-text' }, el('b', { text: d.titel || '(ohne Titel)' }),
        el('span', { class: 'leise klein', text: [k ? k.name : '', datumText(d.datum)].filter(Boolean).join(' · ') }), tagsVon(d)));
  }

  // --- Detail ---

  async function detail(id) {
    let d;
    try { d = await L.api('GET', '/api/dokumente/' + id); } catch (e) { L.meldung(e.message, true); return; }
    const titel = el('input', { value: d.titel, maxlength: 128, required: true });
    const datum = el('input', { type: 'date', value: d.datum || '' });
    const korr = auswahl(ST.korrespondenten, d.korrespondent);
    const typ = auswahl(ST.typen, d.typ);
    const tags = tagWahl(ST.tags, d.tags);
    const notizOrt = el('div', { class: 'stapel', style: 'gap:6px' });
    const notizFeld = el('textarea', { rows: 2, maxlength: 5000, placeholder: 'Notiz hinzufügen …' });
    const notizen = liste => L.setzen(notizOrt, liste.length ? liste.map(n => el('div', { class: 'zeile dok-notiz' },
      el('span', { class: 'hinweis-text', style: 'flex:1', text: n.text }), el('span', { class: 'leise klein mono', text: n.erstellt ? datumText(n.erstellt.slice(0, 10)) : '' }),
      el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Notiz löschen', onclick: async () => {
        try { notizen((await L.api('POST', '/api/dokumente/' + id + '/notiz/' + n.id + '/loeschen', {})).notizen); } catch (e) { L.meldung(e.message, true); }
      } }, L.symbol('muell')))) : el('p', { class: 'leise klein', text: 'Noch keine Notiz.' }));
    notizen(d.notizen);
    const notizNeu = async () => {
      if (!notizFeld.value.trim()) return;
      try { notizen((await L.api('POST', '/api/dokumente/' + id + '/notiz', { text: notizFeld.value })).notizen); notizFeld.value = ''; }
      catch (e) { L.meldung(e.message, true); }
    };
    const bild = el('img', { src: '/api/dokumente/' + id + '/thumb', alt: 'Vorschaubild', class: 'dok-gross' });
    bild.addEventListener('error', () => bild.remove());
    const r = await L.dialog({
      titel: d.titel || 'Dokument', breit: true, knopf: 'Speichern',
      inhalt: el('div', { class: 'dok-detail' },
        el('div', { class: 'stapel', style: 'gap:8px' },
          el('a', { href: '/api/dokumente/' + id + '/preview', target: '_blank', rel: 'noopener', class: 'dok-vorschau', title: 'Vorschau in neuem Tab öffnen' }, bild),
          el('div', { class: 'zeile' },
            el('a', { class: 'knopf klein', href: '/api/dokumente/' + id + '/preview', target: '_blank', rel: 'noopener' }, L.symbol('auge'), 'Vorschau'),
            el('button', { type: 'button', class: 'klein', onclick: () => L.herunterladen('/api/dokumente/' + id + '/download').catch(e => L.meldung(e.message, true)) },
              L.symbol('laden'), 'Original'))),
        el('div', { class: 'stapel', style: 'gap:10px' },
          L.feld('Titel', titel),
          el('div', { class: 'felder zwei' }, L.feld('Dokumentdatum', datum), L.feld('Dokumenttyp', typ)),
          L.feld('Korrespondent', korr),
          el('div', { class: 'feld' }, 'Tags', tags.knoten),
          el('b', { text: 'Notizen' }), notizOrt,
          el('div', { class: 'zeile', style: 'flex-wrap:nowrap;align-items:flex-end' }, notizFeld,
            el('button', { type: 'button', class: 'klein', onclick: notizNeu }, L.symbol('plus'), 'Notiz')))),
      speichern: () => L.api('POST', '/api/dokumente/' + id, { titel: titel.value, datum: datum.value, korrespondent: korr.value || 0,
        typ: typ.value || 0, tags: tags.wert() }),
    });
    if (r) { L.meldung('Gespeichert.'); laden(false); }
  }

  // --- Hochladen (auch fuer Exporte: Dokumente.ablegen) ---

  async function senden(datei, angaben) {
    const p = new URLSearchParams({ name: datei.name || 'dokument.pdf', titel: angaben.titel || '', datum: angaben.datum || '',
      korrespondent: angaben.korrespondent || '0', typ: angaben.typ || '0', tags: (angaben.tags || []).join(',') });
    let antwort, inhalt = {};
    try {
      antwort = await fetch('/api/dokumente/hochladen?' + p, { method: 'POST', credentials: 'same-origin',
        headers: { 'X-Lehrerkalender': '1', 'Content-Type': datei.type || 'application/octet-stream' }, body: datei });
      try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
    } catch (e) { throw new Error('Keine Verbindung zum Server.'); }
    if (!antwort.ok) throw new Error(inhalt.fehler || 'Hochladen fehlgeschlagen.');
    return inhalt.task;
  }

  // Paperless verarbeitet asynchron (OCR): ein paar Mal nachfragen, dann aufgeben statt endlos zu warten
  function warten(task, fertig) {
    let n = 0;
    const timer = setInterval(async () => {
      n += 1;
      if (n > 20 || !task) { clearInterval(timer); if (fertig) fertig(null); return; }
      try {
        const a = await L.api('GET', '/api/dokumente/aufgabe?id=' + encodeURIComponent(task));
        if (a.stand === 'SUCCESS') { clearInterval(timer); L.meldung('Das Dokument ist in Paperless angekommen.'); if (fertig) fertig(a.dokument); }
        else if (a.stand === 'FAILURE') { clearInterval(timer); L.meldung('Paperless meldet einen Fehler: ' + (a.fehler || 'unbekannt'), true); }
      } catch (e) { /* naechster Versuch */ }
    }, 3000);
  }

  async function hochladen() {
    const datei = el('input', { type: 'file', required: true });
    const titel = el('input', { maxlength: 128, required: true });
    const datum = el('input', { type: 'date' });
    const korr = auswahl(ST.korrespondenten, 0);
    const typ = auswahl(ST.typen, 0);
    const tags = tagWahl(ST.tags, []);
    datei.addEventListener('change', () => { const f = datei.files[0]; if (f && !titel.value) titel.value = f.name.replace(/\.[^.]+$/, ''); });
    const upTag = nachId(ST.tags, ST.upload_tag), pfad = nachId(ST.pfade, ST.pfad);
    const task = await L.dialog({
      titel: 'Dokument hochladen', knopf: 'Hochladen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        L.feld('Datei', datei, 'höchstens 100 MB'),
        L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Dokumentdatum', datum, 'leer = erkennt Paperless'), L.feld('Dokumenttyp', typ)),
        L.feld('Korrespondent', korr),
        el('div', { class: 'feld' }, 'Weitere Tags', tags.knoten),
        el('p', { class: 'leise klein', text: 'Automatisch: ' + [upTag ? 'Tag „' + upTag.name + '“' : '', pfad ? 'Speicherpfad „' + pfad.name + '“' : '']
          .filter(Boolean).join(', ') + (upTag || pfad ? '.' : 'nichts (Upload-Tag und Speicherpfad unter Einstellungen › Konto).') })),
      speichern: () => {
        if (!datei.files[0]) throw new Error('Bitte eine Datei wählen.');
        return senden(datei.files[0], { titel: titel.value, datum: datum.value, korrespondent: korr.value, typ: typ.value, tags: tags.wert() });
      },
    });
    if (task === null) return;
    L.meldung('Hochgeladen – Paperless verarbeitet die Datei …');
    warten(task, () => { if (ergebnisOrt && ergebnisOrt.isConnected) neuLaden(); });
  }

  // --- Einstellungen › Konto: Paperless verbinden ---

  function kontoKarte() {
    const ort_ = el('div', { class: 'karte stapel' });
    const kopf = chip => el('div', { class: 'zeile' }, el('h2', { text: 'Dokumente (Paperless)' }), el('span', { class: 'rechts' }, chip));
    const text = el('p', { class: 'leise klein', text: 'Dein eigenes Paperless-ngx im Lehrerkalender: Dokumente suchen, ansehen und hochladen. ' +
      'Adresse und API-Token bleiben auf dem Server und gehen nie an den Browser. Steht Paperless zuhause, braucht der Container ' +
      'eine Route ins Heimnetz (Admin › System › VPN, „Weitere Ziele“).' });

    async function laden() {
      let k;
      try { k = await L.api('GET', '/api/dokumente/konfig'); } catch (e) { L.setzen(ort_, kopf(null), el('div', { class: 'banner warnung', text: e.message })); return; }
      if (!k.verbunden) return verbinden(k);
      let st = null, fehler = null;
      try { st = await L.api('GET', '/api/dokumente/stammlisten'); } catch (e) { fehler = e.message; }
      const namen = (liste, ids) => ids.map(id => (nachId(liste, id) || { name: '#' + id }).name).join(', ');
      L.setzen(ort_, kopf(el('span', { class: 'chip gruen', text: 'verbunden' })), text,
        el('dl', { class: 'vpn-daten klein' },
          el('dt', { text: 'Adresse' }), el('dd', { class: 'mono', text: k.url }),
          el('dt', { text: 'Anzeige-Tags' }), el('dd', { text: k.tags.length ? (st ? namen(st.tags, k.tags) : k.tags.length + ' Tags') : 'keine – alle Dokumente' }),
          el('dt', { text: 'Upload-Tag' }), el('dd', { text: k.upload_tag ? (st ? namen(st.tags, [k.upload_tag]) : '#' + k.upload_tag) : '–' }),
          el('dt', { text: 'Speicherpfad' }), el('dd', { text: k.pfad ? (st ? namen(st.pfade, [k.pfad]) : '#' + k.pfad) : '–' })),
        fehler ? el('div', { class: 'banner warnung klein', text: fehler }) : null,
        el('div', { class: 'zeile' },
          st ? el('button', { type: 'button', class: 'haupt', onclick: () => auswahlDialog(k, st) }, L.symbol('stift'), 'Tags und Pfad') : null,
          el('button', { type: 'button', onclick: () => verbinden(k, true) }, 'Adresse/Token ändern'),
          el('button', { type: 'button', class: 'warnen', onclick: trennen }, 'Trennen'),
          el('a', { class: 'knopf leicht', href: '#dokumente' }, L.symbol('extern'), 'Öffnen')));
    }

    function verbinden(k, aendern) {
      const url = el('input', { value: k.url || '', required: true, placeholder: 'z. B. http://192.168.5.20:8000', autocomplete: 'off' });
      const token = el('input', { type: 'password', autocomplete: 'off', required: !k.verbunden,
        placeholder: k.verbunden ? 'leer = bisheriger Token' : 'aus Paperless: Profil › API-Token' });
      L.setzen(ort_, kopf(el('span', { class: 'chip', text: k.verbunden ? 'verbunden' : 'aus' })), text,
        k.fehler ? el('div', { class: 'banner warnung klein', text: k.fehler }) : null,
        el('form', { class: 'stapel', style: 'gap:10px', onsubmit: async ev => {
          ev.preventDefault();
          try {
            const r = await L.api('POST', '/api/dokumente/konfig', { url: url.value, token: token.value, tags: k.tags || [],
              upload_tag: k.upload_tag || 0, pfad: k.pfad || 0 });
            L.meldung('Verbunden: ' + r.anzahl + (r.anzahl === 1 ? ' Dokument' : ' Dokumente') + ' sichtbar.');
            S.konto.paperless = true;
            navigation('einstellungen');
            laden();
          } catch (e) { L.meldung(e.message, true); }
        } },
        L.feld('Adresse von Paperless', url, 'wie im Browser, ohne /api'),
        L.feld('API-Token', token, 'Paperless: oben rechts dein Name › Mein Profil › API-Auth-Token'),
        el('div', { class: 'zeile' }, el('button', { type: 'submit', class: 'haupt' }, 'Verbinden'),
          aendern ? el('button', { type: 'button', onclick: laden }, 'Abbrechen') : null)));
    }

    async function auswahlDialog(k, st) {
      const tags = tagWahl(st.tags, k.tags);
      const upTag = auswahl(st.tags, k.upload_tag, '– kein Tag –');
      const pfad = auswahl(st.pfade, k.pfad, '– Paperless entscheidet –');
      const r = await L.dialog({
        titel: 'Tags und Speicherpfad', breit: true,
        inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
          el('div', { class: 'feld' }, 'Anzeige-Tags: Der Lehrerkalender zeigt Dokumente mit einem dieser Tags (keiner gewählt = alle)', tags.knoten),
          el('div', { class: 'felder zwei' }, L.feld('Upload-Tag (bekommt jedes hochgeladene Dokument)', upTag),
            L.feld('Speicherpfad für Uploads', pfad)),
          el('p', { class: 'leise klein', text: 'Fehlt ein Tag oder Pfad, lege ihn in Paperless an – der Lehrerkalender legt dort nichts an.' })),
        speichern: () => L.api('POST', '/api/dokumente/konfig', { url: k.url, token: '', tags: tags.wert(), upload_tag: upTag.value || 0, pfad: pfad.value || 0 }),
      });
      if (r) { L.meldung('Gespeichert.'); laden(); }
    }

    async function trennen() {
      const r = await L.dialog({ titel: 'Paperless trennen?', knopf: 'Trennen', gefaehrlich: true,
        inhalt: el('p', { text: 'Adresse und Token werden hier gelöscht. In Paperless selbst ändert sich nichts.' }),
        speichern: () => L.api('POST', '/api/dokumente/konfig/loeschen', {}) });
      if (!r) return;
      S.konto.paperless = false;
      navigation('einstellungen');
      laden();
    }

    laden();
    return ort_;
  }

  return { zeigen, kontoKarte, senden, warten };
})();
