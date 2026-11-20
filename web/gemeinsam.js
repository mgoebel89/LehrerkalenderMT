// Gemeinsame Hilfen fuer alle Seiten (Bauweise wie im TrackingDRS): Schnittstelle, DOM-Bau ohne innerHTML, Meldungen,
// Overlays (jede Entscheidung in einem Fenster: am PC in der Mitte, am Handy als Blatt von unten), Symbole.
'use strict';

const L = {
  NAME: 'Lehrerkalender MT',

  async api(methode, url, daten) {
    const kopf = { 'X-Lehrerkalender': '1' };
    if (daten !== undefined) kopf['Content-Type'] = 'application/json';
    let antwort;
    try {
      antwort = await fetch(url, { method: methode, headers: kopf, credentials: 'same-origin',
        body: daten !== undefined ? JSON.stringify(daten) : undefined });
    } catch (e) {
      throw new Error('Keine Verbindung zum Server.');
    }
    let inhalt = {};
    try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
    if (!antwort.ok) {
      const f = new Error(inhalt.fehler || 'Fehler ' + antwort.status);
      f.status = antwort.status;
      throw f;
    }
    return inhalt;
  },

  // el('div', {class: 'karte', onclick: fn}, 'Text', kindElement, [weitere])
  el(tag, attribute, ...kinder) {
    const e = document.createElement(tag);
    for (const [name, wert] of Object.entries(attribute || {})) {
      if (wert === null || wert === undefined || wert === false) continue;
      if (name.startsWith('on')) e.addEventListener(name.slice(2), wert);
      else if (name === 'class') e.className = wert;
      else if (name === 'text') e.textContent = wert;
      else if (name === 'value') e.value = wert;
      else if (name === 'checked') e.checked = true;
      else e.setAttribute(name, wert === true ? '' : wert);
    }
    const anhaengen = k => {
      if (k === null || k === undefined || k === false) return;
      if (Array.isArray(k)) k.forEach(anhaengen);
      else e.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
    };
    kinder.forEach(anhaengen);
    return e;
  },

  leeren(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; },

  setzen(e, ...kinder) {
    L.leeren(e);
    kinder.flat(Infinity).forEach(k => { if (k !== null && k !== undefined && k !== false) e.append(k); });
    return e;
  },

  meldung(text, fehler) {
    let ort = document.getElementById('meldungen');
    if (!ort) { ort = L.el('div', { id: 'meldungen', 'aria-live': 'polite' }); document.body.appendChild(ort); }
    const m = L.el('div', { class: 'meldung' + (fehler ? ' fehler' : ''), text });
    ort.appendChild(m);
    setTimeout(() => m.remove(), fehler ? 7000 : 3500);
  },

  titel(text) { document.title = text ? text + ' · ' + L.NAME : L.NAME; },

  // Strichsymbole im 24er Raster (Lucide-Formen, ISC-Lizenz)
  SYMBOLE: {
    plan: 'M3 3v18h18M7 5h8v3.5H7zM10 10.5h9V14h-9zM7 16h5v2.5H7z',
    heute: 'M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41',
    kann: 'M3 17l2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8',
    rueck: 'M7.9 20A9 9 0 1 0 4 16.1L2 22Z',
    gn: 'M12 2a6 6 0 1 0 0 12a6 6 0 1 0 0-12M15.48 12.89 17 22l-5-3-5 3 1.52-9.11',
    hilfe: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01',
    uebersicht: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
    klassen: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
    archiv: 'M3 4h18v5H3zM5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4',
    lehrkraefte: 'M12 2a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4.2-6 8-6s7 2 8 6M17 11l2 2 4-4',
    einstellungen: 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
    konto: 'M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4.2-6 8-6s7 2 8 6',
    hoch: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
    kamera: 'M3 8a2 2 0 0 1 2-2h2.5l1.5-2h6l1.5 2H19a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 10a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7',
    fotos: 'M3 5h18v14H3zM3 15l5-5 4 4 3-3 6 6M15.5 8.5h.01',
    laden: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
    plus: 'M12 5v14M5 12h14',
    qr: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h3v3h-3zM20 14v.01M14 20h.01M17 17h4v4h-4z',
    auge: 'M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7ZM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
    pakete: 'M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z',
    kalender: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18',
    hoch_pfeil: 'M12 19V5M5 12l7-7 7 7',
    runter_pfeil: 'M12 5v14M19 12l-7 7-7-7',
    extern: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
    kopie: 'M8 8h12v12H8zM16 8V4H4v12h4',
    haken: 'M20 6 9 17l-5-5',
    uhr: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 6v6l4 2',
    pruefen: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z',
    mikro: 'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3',
    stern: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z',
    zu: 'M18 6 6 18M6 6l12 12',
    links: 'M15 18l-6-6 6-6',
    rechts: 'M9 18l6-6-6-6',
    start: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
    pruefung: 'M9 3h6v4H9zM9 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-3M9 14l2 2 4-4',
    formular: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8M8 9h2',
    admin: 'M12 2 4 5v6c0 5 3.4 9.3 8 11 4.6-1.7 8-6 8-11V5zM9 12l2 2 4-4',
    schloss: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
    schluessel: 'M8 11a4 4 0 1 0 0 8a4 4 0 1 0 0-8M10.8 12.2 20 3M17 6l3 3M14.5 8.5l2 2',
    mail: 'M3 5h18v14H3zM3 7l9 6 9-6',
    ok: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M8 12l3 3 5-6',
    warnung: 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
    stift: 'M17 3l4 4L8 20H4v-4z',
    muell: 'M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14',
    refresh: 'M21 12a9 9 0 0 1-15.5 6.2L3 16M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M3 21v-5h5',
    liste: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
    abmelden: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
    jetzt: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M10 8l6 4-6 4z',
    kreis: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18',
    merker: 'M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z',
    ausfall: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18M10 13l4 4M14 13l-4 4',
    zusatz: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18M12 13v6M9 16h6',
    vertretung: 'M17 2l4 4-4 4M3 11v-1a4 4 0 0 1 4-4h14M7 22l-4-4 4-4M21 13v1a4 4 0 0 1-4 4H3',
    verschieben: 'M8 3 4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4',
    offen: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 7v6M12 17h.01',
    spalten: 'M3 4h18v16H3zM9 4v16M15 4v16',
    info: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 16v-4M12 8h.01',
    mehr: 'M5 12h.01M12 12h.01M19 12h.01',
    undo: 'M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',
    pin: 'M12 17v5M8 3h8M9 3v6l-3 4v2h12v-2l-3-4V3',
    frist: 'M4 22V4M4 4h13l-2.5 4 2.5 4H4',
  },

  // Einschaetzung in 4 Stufen: gespeichert wird immer 1 bis 4, die Klasse zeigt Smileys oder Zahlen
  STUFEN: [['😟', 'muss viel üben', 'Ich muss noch viel üben'], ['😐', 'brauche Hilfe', 'Ich brauche noch Hilfe'],
    ['🙂', 'meist allein', 'Ich kann es meistens allein'], ['😀', 'kann es perfekt', 'Ich kann es perfekt']],
  stufeText(wert, zahlen) {
    if (!wert) return '–';
    const s = L.STUFEN[wert - 1];
    return (zahlen ? String(wert) : s[0]) + ' ' + s[1];
  },
  // Vier Knoepfe; aendern(stufe) bei Klick. Ohne aendern nur Anzeige.
  skala(wert, aendern, zahlen) {
    let ort;
    const neu = w => L.el('div', { class: 'skala' }, L.STUFEN.map(([smiley, text], i) => L.el('button', {
      type: 'button', class: w === i + 1 ? 'an' : null, disabled: !aendern,
      onclick: () => { aendern(i + 1); const n = neu(i + 1); ort.replaceWith(n); ort = n; } },
    L.el('b', { text: zahlen ? String(i + 1) : smiley }), text)));
    ort = neu(wert);
    return ort;
  },

  symbol(name) {
    const ns = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'symbol');
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', L.SYMBOLE[name]);
    s.appendChild(p);
    return s;
  },

  // Overlay mit einer Frage. inhalt: Element(e); speichern(form) darf einen Fehler werfen: er erscheint im Fenster.
  // Rueckgabe: Promise mit dem Ergebnis von speichern() oder null bei Abbrechen.
  // weitere: [{ text, speichern(form) }] zusaetzliche Knoepfe vor dem Hauptknopf (z. B. "Entwurf speichern")
  dialog({ titel, inhalt, knopf = 'Speichern', abbrechen = 'Abbrechen', speichern, gefaehrlich = false, breit = false, weitere = [], fuss = null, fokus = true }) {
    return new Promise(fertig => {
      const fehler = L.el('div', { class: 'fehlertext', role: 'alert' });
      const ok = knopf ? L.el('button', { type: 'submit', class: gefaehrlich ? 'warnen' : 'haupt', text: knopf }) : null;
      const alle = [];
      const ausfuehren = async (funktion, knopfEl) => {
        fehler.textContent = '';
        alle.forEach(b => { b.disabled = true; });
        try { schliessen(funktion ? await funktion(form) : true); }
        catch (e) { fehler.textContent = e.message; alle.forEach(b => { b.disabled = false; }); }
      };
      const extra = weitere.map(w => L.el('button', { type: 'button', text: w.text, class: w.klasse || null, onclick: ev => ausfuehren(w.speichern, ev.currentTarget) }));
      const form = L.el('form', { method: 'dialog' },
        L.el('h2', { class: 'dreieck', text: titel }), inhalt, fehler,
        L.el('div', { class: 'knoepfe' + (extra.length ? ' mehr' : '') }, fuss ? L.el('span', { class: 'fuss leise klein' }, fuss) : null,
          abbrechen ? L.el('button', { type: 'button', text: abbrechen, onclick: () => schliessen(null) }) : null, extra, ok));
      alle.push(...extra);
      if (ok) alle.push(ok);
      const d = L.el('dialog', { class: breit ? 'breit' : null }, form);
      const schliessen = wert => { d.close(); d.remove(); fertig(wert); };
      d.addEventListener('cancel', ev => { ev.preventDefault(); schliessen(null); });
      form.addEventListener('submit', ev => { ev.preventDefault(); ausfuehren(speichern, ok); });
      document.body.appendChild(d);
      d.showModal();
      const erstes = form.querySelector('input:not([type=hidden]):not([readonly]), select, textarea');
      // ohne Eingabefeld der Hauptknopf: sonst waehlt die Eingabetaste den ersten Knopf einer Skala aus
      if (erstes && fokus) erstes.focus(); else if (ok) ok.focus();
    });
  },

  TAGE: ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'],
  // '2026-11-05' -> 'Do 05.11.'; mit jahr -> 'Do 05.11.2026'
  tag(iso, jahr) {
    if (!iso) return '';
    const d = new Date(iso.slice(0, 10) + 'T12:00:00');
    return L.TAGE[d.getDay()] + ' ' + iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + (jahr ? iso.slice(0, 4) : '');
  },
  uhr(zeit) { return zeit ? zeit.slice(11, 16) : ''; },
  // '2026-11-05T09:12:00' -> 'heute 09:12' / 'Do 05.11. 09:12'
  wann(zeit) {
    if (!zeit) return '';
    return (zeit.slice(0, 10) === L.heute() ? 'heute' : L.tag(zeit)) + ' ' + zeit.slice(11, 16);
  },
  heute() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  },

  // Knopf in einem Overlay, der das Overlay schliesst und danach etwas anderes tut (z. B. "Entfernen …" mit Rueckfrage)
  nebenknopf(text, aktion, klasse = 'warnen klein') {
    const k = L.el('button', { type: 'button', class: klasse, text, onclick: () => {
      k.closest('dialog').dispatchEvent(new Event('cancel'));
      setTimeout(aktion, 0);
    } });
    return k;
  },

  // Karteireiter je Klasse; hat die Klasse Gruppen (mehrere Straenge), liefert unter die Wahl
  // "ganze Klasse · Gr. 1 · Gr. 2". straenge: [{klasse_id, gruppe_id, klasse, gruppe, themen?}],
  // aktiv: {klasse, gruppe}, waehlen(klasse_id, gruppe_id), rechts: Element am rechten Rand (z. B. Schuljahr).
  klassenReiter(straenge, aktiv, waehlen, rechts) {
    const klassen = [];
    straenge.forEach(s => {
      let k = klassen.find(x => x.id === s.klasse_id);
      if (!k) klassen.push(k = { id: s.klasse_id, name: s.klasse, straenge: [], themen: 0 });
      k.straenge.push(s);
      k.themen += s.themen || 0;
    });
    const reiter = L.el('div', { class: 'karteireiter' },
      L.el('div', { class: 'reiterleiste', role: 'tablist', 'aria-label': 'Klasse' }, klassen.map(k => {
        const an = k.id === aktiv.klasse;
        return L.el('button', { type: 'button', role: 'tab', class: an ? 'an' : null, 'aria-selected': an ? 'true' : 'false',
          title: k.straenge.length > 1 ? 'mit ' + (k.straenge.length - 1) + ' Gruppe(n)' : null,
          onclick: () => { if (!an) { const s = k.straenge.find(x => (x.gruppe_id || null) === null) || k.straenge[0]; waehlen(k.id, s.gruppe_id || null); } } },
        k.name, k.straenge.length > 1 ? L.el('span', { class: 'gr-zahl', text: '◫' }) : null, k.themen ? L.el('small', { text: String(k.themen) }) : null);
      })),
      rechts ? L.el('div', { class: 'reiter-rechts' }, rechts) : null);
    const gruppen = straenge.filter(s => s.klasse_id === aktiv.klasse);
    const unter = gruppen.length > 1 ? L.el('div', { class: 'segment gruppen-wahl', role: 'group', 'aria-label': 'Gruppe' }, gruppen.map(s =>
      L.el('button', { type: 'button', class: (s.gruppe_id || null) === (aktiv.gruppe || null) ? 'an' : null, onclick: () => waehlen(s.klasse_id, s.gruppe_id || null) },
        s.gruppe || 'ganze Klasse', s.themen ? L.el('small', { class: 'leise', text: ' ' + s.themen }) : null))) : null;
    setTimeout(() => { const a = reiter.querySelector('.reiterleiste .an'); if (a) a.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }, 0);
    return { reiter, unter };
  },

  feld(beschriftung, eingabe, hilfe) {
    return L.el('label', { class: 'feld' }, beschriftung, eingabe, hilfe ? L.el('span', { class: 'hilfe', text: hilfe }) : null);
  },

  // PDF in neuem Tab zeigen (Browser-Ansicht: drucken, speichern). Blockt der Browser das Fenster, wird heruntergeladen.
  ansehen(url) {
    const w = window.open(url + (url.includes('?') ? '&' : '?') + 'ansehen=1', '_blank');
    if (w) { w.opener = null; return Promise.resolve(); }
    return L.herunterladen(url);
  },

  async herunterladen(url) {
    // ueber fetch, damit Fehler (z. B. keine Schueler) als Meldung erscheinen statt als leere Seite
    const antwort = await fetch(url, { credentials: 'same-origin' });
    if (!antwort.ok) {
      let text = 'Fehler ' + antwort.status;
      try { text = (await antwort.json()).fehler || text; } catch (e) { /* leer */ }
      throw new Error(text);
    }
    const name = decodeURIComponent(((antwort.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''(.+)$/) || [])[1] || 'datei');
    const blob = await antwort.blob();
    const a = L.el('a', { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  },
};
