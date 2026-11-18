'use strict';
// Admin-Bereich (Stufe A): Konten und Einladungen, Grunddaten (Bildungsgaenge, Stufen, Lernfelder, Zeitraster, Ferien),
// Klassen, Konferenz-Notenschluessel, System (Update, Sicherung, Protokoll). Jede Aenderung laeuft ueber ein Overlay.
const Admin = (() => {
  const el = L.el;
  let ort = null;
  let titel = () => {};
  let G = null;   // letzter Stand der Grunddaten

  const SYSTEMNAME = { tendenz: 'Tendenznoten', zehntel: 'Zehntelnoten', punkte: 'MSS-Punkte' };
  const zeigeNote = s => s.replace('-', '−');

  async function zeigen(bereich, inhaltEl, titelFn) {
    ort = inhaltEl;
    titel = titelFn;
    if (bereich === 'admin-konten') return konten();
    if (bereich === 'admin-grunddaten') return grunddaten();
    if (bereich === 'admin-klassen') return klassen();
    if (bereich === 'admin-noten') return noten();
    if (bereich === 'admin-system') return system();
  }

  function kopf(text, ...knoepfe) {
    titel(text);
    return el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text }), knoepfe);
  }

  async function laden() {
    G = await L.api('GET', '/api/grunddaten');
    return G;
  }

  // POST an eine Grunddaten-Route; Antwort ist der neue Gesamtstand
  async function gd(url, daten) {
    G = await L.api('POST', url, daten || {});
    return G;
  }

  function optionen(liste, gewaehlt, leer) {
    return [leer !== undefined ? el('option', { value: '', text: leer }) : null,
      ...liste.map(x => el('option', { value: x.id, text: x.name, selected: String(x.id) === String(gewaehlt) ? true : null }))];
  }

  // --- Konten und Einladungen ---

  async function konten() {
    const d = await L.api('GET', '/api/admin/konten');
    L.setzen(ort,
      kopf('Konten', el('button', { type: 'button', class: 'haupt', onclick: einladungNeu }, L.symbol('mail'), 'Einladung erzeugen')),
      el('div', { class: 'karte rollbar' },
        el('table', { class: 'liste' },
          el('thead', {}, el('tr', {}, ['Name', 'Kürzel', 'Rolle', '2. Faktor', 'Stand'].map(t => el('th', { text: t })))),
          el('tbody', {}, d.konten.map(k => el('tr', { class: 'klickbar', tabindex: 0, onclick: () => kontoBearbeiten(k),
            onkeydown: ev => { if (ev.key === 'Enter') kontoBearbeiten(k); } },
            el('td', {}, el('b', { text: k.name })), el('td', { class: 'mono', text: k.kuerzel }),
            el('td', {}, el('span', { class: 'chip ' + (k.rolle === 'admin' ? 'blau' : ''), text: k.rolle === 'admin' ? 'Admin' : 'Lehrkraft' })),
            el('td', {}, el('span', { class: 'chip ' + (k.zweiter_faktor ? 'gruen' : ''), text: k.zweiter_faktor ? 'an' : 'aus' })),
            el('td', {}, k.gesperrt ? el('span', { class: 'chip rot', text: 'gesperrt' }) : k.pw_vorlaeufig ? el('span', { class: 'chip gelb', text: 'vorläufiges Passwort' }) : el('span', { class: 'leise', text: 'aktiv' }))))))),
      el('div', { class: 'karte stapel' },
        el('h2', { text: 'Einladungen' }),
        el('p', { class: 'leise klein', text: 'Ein Einladungscode gilt für genau ein Konto. Weitergeben persönlich oder über Teams; der Code wird nicht gemailt.' }),
        d.einladungen.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
          el('thead', {}, el('tr', {}, ['Code', 'Für', 'Rolle', 'gültig bis', 'Stand', ''].map(t => el('th', { text: t })))),
          el('tbody', {}, d.einladungen.map(e => el('tr', {},
            el('td', { class: 'mono', text: e.code }), el('td', { text: e.notiz || '–' }),
            el('td', { text: e.rolle === 'admin' ? 'Admin' : 'Lehrkraft' }), el('td', { class: 'mono', text: L.tag(e.gueltig_bis, true) }),
            el('td', {}, el('span', { class: 'chip ' + ({ offen: 'blau', eingeloest: 'gruen', abgelaufen: '' })[e.stand],
              text: e.stand === 'eingeloest' ? 'eingelöst' + (e.eingeloest_von ? ' · ' + e.eingeloest_von : '') : e.stand })),
            el('td', { class: 'knoepfe' }, e.stand === 'offen' ? [
              el('button', { type: 'button', class: 'klein', onclick: () => einladungZeigen(e) }, L.symbol('kopie'), 'zeigen'),
              el('button', { type: 'button', class: 'warnen klein', onclick: () => einladungWeg(e) }, 'zurückziehen')] : null))))))
          : el('p', { class: 'leise', text: 'Noch keine Einladungen.' })));
  }

  async function kontoBearbeiten(k) {
    const name = el('input', { value: k.name });
    const rolle = el('select', {}, el('option', { value: 'lehrkraft', text: 'Lehrkraft', selected: k.rolle === 'lehrkraft' ? true : null }),
      el('option', { value: 'admin', text: 'Admin', selected: k.rolle === 'admin' ? true : null }));
    const gesperrt = el('input', { type: 'checkbox', checked: k.gesperrt || null });
    const pw = el('input', { type: 'text', autocomplete: 'off', placeholder: 'leer lassen = unverändert' });
    const faktor = el('input', { type: 'checkbox' });
    const r = await L.dialog({
      titel: k.name + ' (' + k.kuerzel + ')',
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name), L.feld('Rolle', rolle),
        el('label', { class: 'haken' }, gesperrt, 'Konto gesperrt (alle Anmeldungen enden sofort)'),
        L.feld('Vorläufiges Passwort setzen', pw, 'Die Lehrkraft muss es bei der nächsten Anmeldung ändern.'),
        k.zweiter_faktor ? el('label', { class: 'haken' }, faktor, 'Zweiten Faktor zurücksetzen (Handy verloren)') : null),
      speichern: () => L.api('POST', '/api/admin/konten/' + k.id, {
        name: name.value, rolle: rolle.value, gesperrt: gesperrt.checked, passwort: pw.value || null,
        zweiter_faktor_zuruecksetzen: faktor.checked }),
    });
    if (r) { L.meldung('Gespeichert.'); konten(); }
  }

  async function einladungNeu() {
    const rolle = el('select', {}, el('option', { value: 'lehrkraft', text: 'Lehrkraft' }), el('option', { value: 'admin', text: 'Admin' }));
    const tage = el('input', { type: 'number', min: 1, max: 60, value: 14, style: 'max-width:110px' });
    const notiz = el('input', { placeholder: 'z. B. Kollege Becker', maxlength: 80 });
    const r = await L.dialog({
      titel: 'Einladung erzeugen', knopf: 'Erzeugen',
      inhalt: el('div', { class: 'felder' }, L.feld('Für wen (nur für dich als Notiz)', notiz), L.feld('Rolle', rolle), L.feld('Gültig (Tage)', tage)),
      speichern: () => L.api('POST', '/api/admin/einladungen', { rolle: rolle.value, tage: Number(tage.value), notiz: notiz.value }),
    });
    if (!r) return;
    await einladungZeigen(r.einladung);
    konten();
  }

  function einladungZeigen(e) {
    const link = location.origin + '/einladung#' + e.code;
    return L.dialog({
      titel: 'Einladungscode', knopf: 'Fertig', abbrechen: null,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('div', { class: 'banner' }, L.symbol('schluessel'), ' ', el('span', { class: 'mono', style: 'font-weight:700;letter-spacing:.08em;font-size:1.1rem', text: e.code })),
        el('p', { class: 'klein' }, 'Gültig bis ', el('b', { text: L.tag(e.gueltig_bis, true) }), ' für ein Konto als ', e.rolle === 'admin' ? 'Admin' : 'Lehrkraft', '.'),
        el('p', { class: 'leise klein' }, 'Link zum Weitergeben: ', el('span', { class: 'mono', style: 'word-break:break-all', text: link })),
        el('div', { class: 'zeile' },
          el('button', { type: 'button', onclick: () => kopieren(e.code) }, L.symbol('kopie'), 'Code kopieren'),
          el('button', { type: 'button', onclick: () => kopieren(link) }, L.symbol('kopie'), 'Link kopieren'))),
    });
  }

  function kopieren(text) {
    navigator.clipboard.writeText(text).then(() => L.meldung('Kopiert.'), () => L.meldung('Kopieren ging nicht, bitte markieren und kopieren.', true));
  }

  async function einladungWeg(e) {
    const ok = await L.dialog({ titel: 'Einladung zurückziehen?', knopf: 'Zurückziehen', gefaehrlich: true,
      inhalt: el('p', {}, 'Der Code ', el('span', { class: 'mono', text: e.code }), ' gilt danach nicht mehr.'),
      speichern: () => L.api('POST', '/api/admin/einladungen/' + e.id + '/zurueckziehen', {}) });
    if (ok) konten();
  }

  // --- Grunddaten: Bildungsgaenge (mit Stufen und Lernfeldern), Zeitraster, Ferien ---

  let reiter = 'bildungsgaenge';

  async function grunddaten() {
    await laden();
    const tab = (id, text, sym) => el('button', { type: 'button', class: reiter === id ? 'an' : null,
      onclick: () => { reiter = id; grunddatenZeichnen(); } }, L.symbol(sym), text);
    grunddatenZeichnen = () => {
      L.setzen(ort,
        kopf('Grunddaten'),
        el('div', { class: 'segment', role: 'group', 'aria-label': 'Grunddaten' },
          tab('bildungsgaenge', 'Bildungsgänge und Lernfelder', 'pakete'), tab('zeitraster', 'Zeitraster', 'uhr'), tab('ferien', 'Schuljahr und Ferien', 'kalender'),
          tab('schule', 'Schule und Logo', 'formular')),
        reiter === 'bildungsgaenge' ? bildungsgaengeAnsicht() : reiter === 'zeitraster' ? zeitrasterAnsicht() : reiter === 'schule' ? schuleAnsicht() : ferienAnsicht());
    };
    grunddatenZeichnen();
  }
  let grunddatenZeichnen = () => {};

  // --- Schule: Logo (fuer App und Dokumente), Name und Webadresse fuer Kopf und Fuss der Dokumente ---
  // Jedes Bild wird im Browser in ein JPEG umgewandelt (weisser Hintergrund, hoechstens 1600 px breit): so bettet der
  // Server es ohne Bildbibliothek in die PDFs ein.
  function alsJpeg(datei) {
    return new Promise((ok, fehler) => {
      const url = URL.createObjectURL(datei);
      const bild = new Image();
      bild.onload = () => {
        const faktor = Math.min(1, 1600 / bild.naturalWidth);
        const c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(bild.naturalWidth * faktor));
        c.height = Math.max(1, Math.round(bild.naturalHeight * faktor));
        const g = c.getContext('2d');
        g.fillStyle = '#fff';
        g.fillRect(0, 0, c.width, c.height);
        g.drawImage(bild, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        ok(c.toDataURL('image/jpeg', 0.92));
      };
      bild.onerror = () => { URL.revokeObjectURL(url); fehler(new Error('Dieses Bild lässt sich nicht öffnen. Bitte ein PNG oder JPEG wählen.')); };
      bild.src = url;
    });
  }

  // Schul-Vorlagen der Formulare (PDF mit Formularfeldern); liegen nur in der Datenbank, nicht im Repo
  function vorlagenKarte() {
    const v = (G.formularvorlagen || {}).stundenplanaenderung;
    const datei = el('input', { type: 'file', accept: 'application/pdf,.pdf' });
    const senden = async wert => {
      try { G.formularvorlagen = (await L.api('POST', '/api/formularvorlage', { art: 'stundenplanaenderung', pdf: wert, name: datei.files[0] ? datei.files[0].name : '' })).vorlagen;
        L.meldung(wert ? 'Vorlage gespeichert.' : 'Vorlage entfernt.'); grunddatenZeichnen(); }
      catch (e) { L.meldung(e.message, true); }
    };
    datei.addEventListener('change', () => {
      const f = datei.files[0];
      if (!f) return;
      const leser = new FileReader();
      leser.onload = () => senden(leser.result);
      leser.readAsDataURL(f);
    });
    return el('div', { class: 'karte stapel' }, el('h3', { text: 'Formularvorlagen' }),
      el('div', { class: 'zeile' }, el('b', { text: 'Stundenplanänderung / Beurlaubung' }),
        v ? el('span', { class: 'chip gruen', text: 'hinterlegt' }) : el('span', { class: 'chip gelb', text: 'fehlt' })),
      v ? el('p', { class: 'leise klein', text: (v.name || 'PDF') + ' · seit ' + L.tag(v.hochgeladen.slice(0, 10), true) }) : null,
      el('p', { class: 'leise klein', text: 'Das ausfüllbare Schul-PDF (mit Formularfeldern). Es liegt nur hier in der Datenbank, nicht im öffentlichen Programmcode.' }),
      el('div', { class: 'zeile' }, L.feld(v ? 'Andere Vorlage' : 'PDF hochladen', datei), v ? L.nebenknopf('Entfernen', () => senden('')) : null));
  }

  function schuleAnsicht() {
    const sch = G.schule;
    const name = el('input', { maxlength: 120, value: sch.name });
    const web = el('input', { maxlength: 120, value: sch.web, placeholder: 'www.drsneuwied.de' });
    const datei = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif' });
    const speichernLogo = async wert => {
      try { G.schule = await L.api('POST', '/api/schule', { logo: wert }); L.meldung(wert ? 'Logo gespeichert.' : 'Logo entfernt.'); grunddatenZeichnen(); }
      catch (e) { L.meldung(e.message, true); }
    };
    datei.addEventListener('change', async () => {
      if (!datei.files[0]) return;
      try { await speichernLogo(await alsJpeg(datei.files[0])); } catch (e) { L.meldung(e.message, true); }
    });
    return el('div', { class: 'zwei-spalten' },
      el('div', { class: 'karte stapel' }, el('h3', { text: 'Schullogo' }),
        sch.logo ? el('div', { class: 'logo-vorschau' }, el('img', { src: '/api/schule/logo?v=' + encodeURIComponent(sch.logo_stand), alt: 'Schullogo' }))
          : el('p', { class: 'leise', text: 'Noch kein Logo. Ohne Logo steht der Schulname im Kopf der Dokumente.' }),
        el('p', { class: 'leise klein', text: 'Erscheint auf der Anmeldeseite, in der Kopfzeile und oben links auf allen Dokumenten (PDF). Am besten das Logo im Querformat; PNG mit Transparenz bekommt einen weißen Hintergrund.' }),
        el('div', { class: 'zeile' }, L.feld(sch.logo ? 'Anderes Logo hochladen' : 'Logo hochladen', datei),
          sch.logo ? L.nebenknopf('Logo entfernen', () => speichernLogo('')) : null)),
      vorlagenKarte(),
      el('div', { class: 'karte stapel' }, el('h3', { text: 'Angaben für die Dokumente' }),
        L.feld('Schulname', name, 'steht im Kopf, wenn kein Logo da ist'),
        L.feld('Webadresse', web, 'steht im Fuß unter dem DRS-Farbband'),
        el('div', {}, el('button', { type: 'button', class: 'haupt', onclick: async () => {
          try { G.schule = await L.api('POST', '/api/schule', { name: name.value, web: web.value }); L.meldung('Gespeichert.'); }
          catch (e) { L.meldung(e.message, true); }
        } }, L.symbol('ok'), 'Speichern'))));
  }

  function bildungsgaengeAnsicht() {
    return el('div', { class: 'stapel' },
      el('div', {}, el('button', { type: 'button', class: 'haupt', onclick: () => bildungsgangBearbeiten(null) }, L.symbol('plus'), 'Bildungsgang')),
      G.bildungsgaenge.length ? null : el('div', { class: 'leer', text: 'Noch kein Bildungsgang. Beginne z. B. mit „Mechatroniker/in“ (Lernfelder) oder „Fachschule Technik“ (Module).' }),
      G.bildungsgaenge.map(b => {
        const einheit = b.einheit === 'modul' ? 'Modul' : 'Lernfeld';
        const stufeName = id => (b.stufen.find(s => s.id === id) || {}).name || '–';
        return el('div', { class: 'karte stapel' + (b.aktiv ? '' : ' aus') },
          el('div', { class: 'zeile' },
            el('h2', { text: b.name }), b.kuerzel ? el('span', { class: 'chip', text: b.kuerzel }) : null,
            el('span', { class: 'chip', text: b.einheit === 'modul' ? 'Module' : 'Lernfelder' }),
            b.aktiv ? null : el('span', { class: 'chip', text: 'nicht aktiv' }),
            el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => bildungsgangBearbeiten(b) }, L.symbol('stift'), 'bearbeiten'))),
          el('div', { class: 'zeile' }, el('span', { class: 'etikett', text: b.einheit === 'modul' ? 'Semester' : 'Stufen' }),
            b.stufen.map(s => el('button', { type: 'button', class: 'chip-knopf', onclick: () => stufeBearbeiten(b, s) }, s.name)),
            el('button', { type: 'button', class: 'leicht klein', onclick: () => stufeBearbeiten(b, null) }, L.symbol('plus'), b.einheit === 'modul' ? 'Semester' : 'Stufe')),
          el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
            el('thead', {}, el('tr', {}, [einheit, 'Name', b.einheit === 'modul' ? 'beginnt in' : 'Stufe', 'Stundenansatz'].map((t, i) =>
              el('th', { text: t, style: i === 3 ? 'text-align:right' : null })))),
            el('tbody', {}, b.lernfelder.length ? b.lernfelder.map(lf => el('tr', { class: 'klickbar' + (lf.aktiv ? '' : ' aus'), tabindex: 0,
              onclick: () => lernfeldBearbeiten(b, lf), onkeydown: ev => { if (ev.key === 'Enter') lernfeldBearbeiten(b, lf); } },
              el('td', { class: 'mono' }, el('b', { text: lf.nummer })), el('td', { text: lf.name }), el('td', { text: stufeName(lf.stufe_id) }),
              el('td', { class: 'mono', style: 'text-align:right' }, lf.stunden + ' Std',
                Object.keys(lf.anteile).length ? el('div', { class: 'leise klein', text: Object.entries(lf.anteile).map(([sid, std]) => stufeName(Number(sid)) + ' ' + std).join(' · ') }) : null)))
              : el('tr', {}, el('td', { colspan: 4, class: 'leise', text: 'Noch keine ' + (b.einheit === 'modul' ? 'Module' : 'Lernfelder') + '.' }))))),
          el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => lernfeldBearbeiten(b, null) }, L.symbol('plus'), einheit)));
      }));
  }

  async function bildungsgangBearbeiten(b) {
    const name = el('input', { value: b ? b.name : '', placeholder: 'z. B. Mechatroniker/in' });
    const kuerzel = el('input', { value: b ? b.kuerzel : '', placeholder: 'z. B. BSMT', maxlength: 12 });
    const einheit = el('select', {}, el('option', { value: 'lernfeld', text: 'Lernfelder (Berufsschule)', selected: !b || b.einheit === 'lernfeld' ? true : null }),
      el('option', { value: 'modul', text: 'Module (Fachschule)', selected: b && b.einheit === 'modul' ? true : null }));
    const aktiv = el('input', { type: 'checkbox', checked: !b || b.aktiv ? true : null });
    const r = await L.dialog({
      titel: b ? b.name : 'Neuer Bildungsgang',
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name), L.feld('Kürzel', kuerzel), L.feld('Gegliedert in', einheit),
        el('label', { class: 'haken' }, aktiv, 'aktiv (nicht aktive erscheinen nirgends zur Auswahl)'),
        b ? L.nebenknopf('Bildungsgang löschen …', () => loeschenFragen('Bildungsgang „' + b.name + '“ löschen?',
          'Mit allen Stufen, Lernfeldern und dem eigenen Zeitraster. Geht nur, solange es keine Klassen dazu gibt.', '/api/admin/bildungsgang/' + b.id + '/loeschen')) : null),
      speichern: () => gd(b ? '/api/admin/bildungsgang/' + b.id : '/api/admin/bildungsgang',
        { name: name.value, kuerzel: kuerzel.value, einheit: einheit.value, aktiv: aktiv.checked }),
    });
    if (r) grunddatenZeichnen();
  }

  async function stufeBearbeiten(b, s) {
    const name = el('input', { value: s ? s.name : '', placeholder: b.einheit === 'modul' ? 'z. B. 1. Semester' : 'z. B. Fachstufe I' });
    const r = await L.dialog({
      titel: s ? s.name : (b.einheit === 'modul' ? 'Neues Semester' : 'Neue Stufe') + ' · ' + b.name,
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name),
        s ? L.nebenknopf('Löschen …', () => loeschenFragen('„' + s.name + '“ löschen?', 'Lernfelder dieser Stufe verlieren ihre Zuordnung.', '/api/admin/stufe/' + s.id + '/loeschen')) : null),
      speichern: () => gd(s ? '/api/admin/stufe/' + s.id : '/api/admin/stufe', { name: name.value, bildungsgang_id: b.id }),
    });
    if (r) grunddatenZeichnen();
  }

  async function lernfeldBearbeiten(b, lf) {
    const modul = b.einheit === 'modul';
    const nummer = el('input', { value: lf ? lf.nummer : '', placeholder: modul ? 'M 4' : 'LF 7', maxlength: 12, style: 'max-width:120px' });
    const name = el('input', { value: lf ? lf.name : '', placeholder: modul ? 'Automatisierungstechnik' : 'Steuerungen für Anlagen programmieren' });
    const stufe = el('select', {}, optionen(b.stufen, lf ? lf.stufe_id : '', '–'));
    const stunden = el('input', { type: 'number', min: 0, max: 2000, value: lf ? lf.stunden : '', style: 'max-width:120px' });
    const aktiv = el('input', { type: 'checkbox', checked: !lf || lf.aktiv ? true : null });
    const anteile = {};
    const anteilFelder = modul && b.stufen.length ? el('div', { class: 'felder zwei' }, b.stufen.map(s => {
      anteile[s.id] = el('input', { type: 'number', min: 0, max: 2000, value: lf && lf.anteile[s.id] ? lf.anteile[s.id] : '' });
      return L.feld(s.name + ' (Std)', anteile[s.id]);
    })) : null;
    const r = await L.dialog({
      titel: lf ? lf.nummer + ' ' + lf.name : (modul ? 'Neues Modul' : 'Neues Lernfeld') + ' · ' + b.name,
      inhalt: el('div', { class: 'felder' },
        el('div', { class: 'felder zwei' }, L.feld('Nummer', nummer), L.feld('Stundenansatz gesamt', stunden, 'Unterrichtsstunden laut Lehrplan')),
        L.feld('Name', name), L.feld(modul ? 'Beginnt im Semester' : 'Stufe', stufe),
        anteilFelder ? el('div', { class: 'stapel', style: 'gap:6px' }, el('span', { class: 'etikett', text: 'Stunden je Semester (optional)' }), anteilFelder) : null,
        el('label', { class: 'haken' }, aktiv, 'aktiv'),
        lf ? L.nebenknopf('Löschen …', () => loeschenFragen(lf.nummer + ' löschen?', 'Ab Stufe C hängen Themen der Bibliothek daran; dann lieber auf „nicht aktiv“ stellen.', '/api/admin/lernfeld/' + lf.id + '/loeschen')) : null),
      speichern: () => {
        const a = {};
        Object.entries(anteile).forEach(([sid, inp]) => { if (inp.value) a[sid] = Number(inp.value); });
        return gd(lf ? '/api/admin/lernfeld/' + lf.id : '/api/admin/lernfeld', { bildungsgang_id: b.id, nummer: nummer.value, name: name.value,
          stufe_id: stufe.value || null, stunden: Number(stunden.value || 0), aktiv: aktiv.checked, anteile: a });
      },
    });
    if (r) grunddatenZeichnen();
  }

  async function loeschenFragen(titelText, text, url, danach) {
    const r = await L.dialog({ titel: titelText, knopf: 'Löschen', gefaehrlich: true, inhalt: el('p', { text }), speichern: () => gd(url) });
    if (r) (danach || grunddatenZeichnen)();
  }

  function zeitrasterAnsicht() {
    const karte = (titelText, bid, bloecke, hinweis) => el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, el('h2', { text: titelText }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => zeitrasterBearbeiten(titelText, bid, bloecke) }, L.symbol('stift'), 'bearbeiten'))),
      hinweis ? el('p', { class: 'leise klein', text: hinweis }) : null,
      bloecke.length ? el('table', { class: 'liste' }, el('tbody', {}, bloecke.map(z => el('tr', {},
        el('td', { text: z.bezeichnung }), el('td', { class: 'mono', style: 'text-align:right', text: z.beginn + '–' + z.ende })))))
        : el('p', { class: 'leise', text: bid ? 'Kein eigenes Raster: es gilt das Raster der Schule.' : 'Noch kein Zeitraster.' }));
    return el('div', { class: 'stapel' },
      el('p', { class: 'leise', style: 'max-width:75ch', text: 'Ein Raster für die ganze Schule. Ein Bildungsgang mit anderen Zeiten (z. B. Fachschule am Abend) bekommt ein eigenes; seine Klassen nutzen dann dieses.' }),
      el('div', { class: 'zwei-spalten' },
        karte('Schule', null, G.zeitraster_schule, 'Gilt für alle Bildungsgänge ohne eigenes Raster.'),
        G.bildungsgaenge.map(b => karte(b.name, b.id, b.zeitraster, null))));
  }

  async function zeitrasterBearbeiten(titelText, bid, bloecke) {
    const zeilenOrt = el('div', { class: 'stapel', style: 'gap:6px' });
    const zeilen = [];
    const zeileNeu = z => {
      const bez = el('input', { value: z ? z.bezeichnung : (zeilen.length + 1) + '. Block', maxlength: 20, 'aria-label': 'Bezeichnung' });
      const beginn = el('input', { type: 'time', value: z ? z.beginn : '', 'aria-label': 'Beginn' });
      const ende = el('input', { type: 'time', value: z ? z.ende : '', 'aria-label': 'Ende' });
      const zeile = { bez, beginn, ende };
      const div = el('div', { class: 'raster-zeile' }, bez, beginn, el('span', { class: 'leise', text: '–' }), ende,
        el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Block entfernen', onclick: () => { zeilen.splice(zeilen.indexOf(zeile), 1); div.remove(); } }, L.symbol('zu')));
      zeilen.push(zeile);
      zeilenOrt.appendChild(div);
    };
    bloecke.forEach(zeileNeu);
    if (!bloecke.length && !bid) zeileNeu(null);
    const r = await L.dialog({
      titel: 'Zeitraster · ' + titelText,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        bid ? el('p', { class: 'leise klein', text: 'Alle Blöcke entfernen = es gilt wieder das Raster der Schule.' }) : null,
        zeilenOrt,
        el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => zeileNeu(null) }, L.symbol('plus'), 'Block'))),
      speichern: () => gd('/api/admin/zeitraster', { bildungsgang_id: bid,
        bloecke: zeilen.map(z => ({ bezeichnung: z.bez.value, beginn: z.beginn.value, ende: z.ende.value })) }),
    });
    if (r) grunddatenZeichnen();
  }

  function ferienAnsicht() {
    return el('div', { class: 'stapel', style: 'max-width:760px' }, schuljahrKarte(), Abos.karte(true, async () => { await laden(); grunddatenZeichnen(); }),
      abWochenKarte(), el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, el('h2', { text: 'Ferien und freie Tage' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt klein', onclick: ferienNeu }, L.symbol('plus'), 'Ferien'))),
      el('p', { class: 'leise klein', text: 'Gelten für alle Klassen. Gesetzliche Feiertage in Rheinland-Pfalz (auch Fronleichnam und Allerheiligen) rechnet das Programm selbst aus; an diesen Tagen fällt der Stundenplan weg.' }),
      G.ferien.length ? el('table', { class: 'liste' }, el('tbody', {}, G.ferien.map(f => el('tr', {},
        el('td', {}, el('b', { text: f.name })), el('td', { class: 'mono', text: L.tag(f.von, true) + (f.bis !== f.von ? ' – ' + L.tag(f.bis, true) : '') }),
        el('td', { class: 'knoepfe' }, f.abo ? el('span', { class: 'chip', title: 'kommt aus dem Kalender-Abo', text: 'Abo: ' + f.abo })
          : el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Entfernen',
            onclick: () => loeschenFragen(f.name + ' entfernen?', 'Die Ferien verschwinden aus allen Kalendern.', '/api/admin/ferien/' + f.id + '/loeschen') }, L.symbol('muell')))))))
        : el('p', { class: 'leise', text: 'Noch keine Ferien eingetragen.' })));
  }

  // Schuljahre: erster und letzter Unterrichtstag (die Planung jeder Klasse gilt je Schuljahr)
  function schuljahrKarte() {
    return el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, el('h2', { text: 'Schuljahr' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt klein', onclick: () => schuljahrBearbeiten(null) }, L.symbol('plus'), 'Schuljahr'))),
      el('p', { class: 'leise klein', text: 'Erster und letzter Unterrichtstag. Die Planung jeder Klasse läuft über ein Schuljahr; was danach nicht mehr passt, zeigt sie rot.' }),
      G.schuljahre.length ? el('table', { class: 'liste' }, el('tbody', {}, G.schuljahre.map(j => el('tr', { class: 'klickbar', tabindex: '0',
        onclick: () => schuljahrBearbeiten(j), onkeydown: ev => { if (ev.key === 'Enter') schuljahrBearbeiten(j); } },
      el('td', {}, el('b', { text: j.name })), el('td', { class: 'mono', text: L.tag(j.beginn, true) + ' – ' + L.tag(j.ende, true) }),
      el('td', { class: 'knoepfe' }, L.symbol('stift'))))))
        : el('p', { class: 'leise', text: 'Noch kein Schuljahr eingetragen.' }));
  }

  async function schuljahrBearbeiten(j) {
    const name = el('input', { maxlength: 20, value: j ? j.name : '', placeholder: 'z. B. 2026/27' });
    const beginn = el('input', { type: 'date', value: j ? j.beginn : '' });
    const ende = el('input', { type: 'date', value: j ? j.ende : '' });
    const r = await L.dialog({
      titel: j ? 'Schuljahr ' + j.name : 'Neues Schuljahr',
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name),
        el('div', { class: 'felder zwei' }, L.feld('Erster Unterrichtstag', beginn), L.feld('Letzter Unterrichtstag', ende)),
        j ? el('div', {}, L.nebenknopf('Schuljahr löschen …', () => loeschenFragen('Schuljahr ' + j.name + ' löschen?',
          'Geht nur, solange es darin noch keine Planung gibt.', '/api/admin/schuljahr/' + j.id + '/loeschen'))) : null),
      speichern: () => gd(j ? '/api/admin/schuljahr/' + j.id : '/api/admin/schuljahr', { name: name.value, beginn: beginn.value, ende: ende.value }),
    });
    if (r) grunddatenZeichnen();
  }

  // A/B-Wochen nach Kalenderwoche: welche KW sind A-Wochen?
  function abWochenKarte() {
    const wahl = el('select', { 'aria-label': 'A-Wochen', style: 'width:auto', onchange: async () => {
      try { await gd('/api/admin/a-woche', { a_woche: wahl.value }); L.meldung('Gespeichert.'); grunddatenZeichnen(); } catch (e) { L.meldung(e.message, true); }
    } }, [['ungerade', 'ungeraden'], ['gerade', 'geraden']].map(([w, t]) =>
      el('option', { value: w, text: t + ' Kalenderwochen', selected: G.a_woche === w ? true : null })));
    return el('div', { class: 'karte stapel' },
      el('h2', { text: 'A- und B-Wochen' }),
      el('div', { class: 'zeile' }, el('span', { text: 'A-Wochen sind die' }), wahl),
      el('p', { class: 'leise klein', text: 'Gilt für alle Stundenpläne mit Einträgen „nur A“ oder „nur B“. Ferien unterbrechen die Folge nicht.' }));
  }

  async function ferienNeu() {
    const name = el('input', { placeholder: 'z. B. Weihnachtsferien' });
    const von = el('input', { type: 'date' });
    const bis = el('input', { type: 'date' });
    const r = await L.dialog({
      titel: 'Ferien eintragen', knopf: 'Eintragen',
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name), el('div', { class: 'felder zwei' }, L.feld('von', von), L.feld('bis', bis, 'leer = ein Tag'))),
      speichern: () => gd('/api/admin/ferien', { name: name.value, von: von.value, bis: bis.value || von.value }),
    });
    if (r) grunddatenZeichnen();
  }

  // --- Klassen ---

  async function klassen() {
    await laden();
    const bg = id => G.bildungsgaenge.find(b => b.id === id);
    const schl = id => G.notenschluessel.find(s => s.id === id);
    L.setzen(ort,
      kopf('Klassen', el('button', { type: 'button', class: 'haupt', onclick: () => klasseBearbeiten(null) }, L.symbol('plus'), 'Klasse')),
      G.bildungsgaenge.length ? null : el('div', { class: 'banner warnung', text: 'Zuerst unter Grunddaten einen Bildungsgang anlegen.' }),
      el('p', { class: 'leise', style: 'max-width:75ch', text: 'Klassen gibt es einmal für alle Lehrkräfte. Daran hängen später geteilte Termine und der Themenstand. Die Schülerlisten führt jede Lehrkraft selbst (Stufe D).' }),
      el('div', { class: 'karte rollbar' }, G.klassen.length ? el('table', { class: 'liste' },
        el('thead', {}, el('tr', {}, ['Klasse', 'Bildungsgang', 'Stufe', 'Unterricht', 'Notenschlüssel', ''].map(t => el('th', { text: t })))),
        el('tbody', {}, G.klassen.map(k => el('tr', { class: 'klickbar' + (k.aktiv ? '' : ' aus'), tabindex: 0, onclick: () => klasseBearbeiten(k),
          onkeydown: ev => { if (ev.key === 'Enter') klasseBearbeiten(k); } },
          el('td', {}, el('b', { text: k.name })), el('td', { text: k.bildungsgang }), el('td', { text: k.stufe || '–' }),
          el('td', { class: 'klein' }, k.beginn || k.ende
            ? el('span', { class: 'chip' + (k.ende && k.ende < L.heute() ? '' : ' gelb'), text: (k.beginn ? 'ab ' + L.tag(k.beginn).trim() + ' ' : '') + (k.ende ? 'bis ' + L.tag(k.ende).trim() : '') })
            : el('span', { class: 'leise', text: 'ganzes Schuljahr' })),
          el('td', {}, k.notenschluessel_id && schl(k.notenschluessel_id) ? el('span', { class: 'chip', text: schl(k.notenschluessel_id).name })
            : el('span', { class: 'leise klein', text: 'wie Bildungsgang' })),
          el('td', {}, k.aktiv ? null : el('span', { class: 'chip', text: 'nicht aktiv' }))))))
        : el('p', { class: 'leise', text: 'Noch keine Klassen.' })));
    void bg;
  }

  async function klasseBearbeiten(k) {
    if (!G.bildungsgaenge.length) { L.meldung('Zuerst einen Bildungsgang anlegen.', true); return; }
    const name = el('input', { value: k ? k.name : '', placeholder: 'z. B. BSMT 24a', maxlength: 30 });
    const bgSel = el('select', {}, optionen(G.bildungsgaenge.filter(b => b.aktiv || (k && b.id === k.bildungsgang_id)), k ? k.bildungsgang_id : G.bildungsgaenge[0].id));
    const stufe = el('select');
    const schl = el('select');
    const aktiv = el('input', { type: 'checkbox', checked: !k || k.aktiv ? true : null });
    const beginn = el('input', { type: 'date', value: k && k.beginn ? k.beginn : '' });
    const ende = el('input', { type: 'date', value: k && k.ende ? k.ende : '' });
    const fuellen = () => {
      const b = G.bildungsgaenge.find(x => String(x.id) === bgSel.value);
      L.setzen(stufe, optionen(b ? b.stufen : [], k ? k.stufe_id : '', '–'));
      L.setzen(schl, optionen(G.notenschluessel.filter(s => s.art === 'konferenz'), k ? k.notenschluessel_id : '', 'wie Bildungsgang (Konferenzschlüssel)'));
    };
    bgSel.addEventListener('change', fuellen);
    fuellen();
    const r = await L.dialog({
      titel: k ? k.name : 'Neue Klasse',
      inhalt: el('div', { class: 'felder' }, L.feld('Name', name), L.feld('Bildungsgang', bgSel), L.feld('Stufe', stufe, 'Zum Schuljahreswechsel von Hand umstellen.'),
        L.feld('Notenschlüssel', schl, 'Nur ändern, wenn die Klasse einen anderen Konferenzschlüssel braucht.'),
        el('div', { class: 'felder zwei' }, L.feld('Erster Unterrichtstag', beginn, 'leer = ab Schuljahresbeginn'),
          L.feld('Letzter Unterrichtstag', ende, 'z. B. Ausschulung vor den Prüfungen; leer = bis Schuljahresende')),
        el('p', { class: 'leise klein', text: 'Außerhalb dieses Zeitraums verschwinden die Stunden der Klasse aus allen Wochenplänen, und die Planung rechnet nur bis zum letzten Unterrichtstag. Stundenpläne müssen dafür nicht geändert werden.' }),
        el('label', { class: 'haken' }, aktiv, 'aktiv'),
        k ? L.nebenknopf('Klasse löschen …', () => loeschenFragen(k.name + ' löschen?', 'Nur sinnvoll für versehentlich angelegte Klassen; sonst „nicht aktiv“.', '/api/admin/klasse/' + k.id + '/loeschen', klassen)) : null),
      speichern: () => gd(k ? '/api/admin/klasse/' + k.id : '/api/admin/klasse', { name: name.value, bildungsgang_id: bgSel.value,
        stufe_id: stufe.value || null, notenschluessel_id: schl.value || null, aktiv: aktiv.checked, beginn: beginn.value || null, ende: ende.value || null }),
    });
    if (r) klassen();
  }

  // --- Konferenz-Notenschluessel ---

  async function noten() {
    await laden();
    const konf = G.notenschluessel.filter(s => s.art === 'konferenz');
    L.setzen(ort,
      kopf('Notenschlüssel'),
      el('p', { class: 'leise', style: 'max-width:75ch', text: 'Je Bildungsgang ein Konferenzschlüssel, wie in der Konferenz vereinbart. Er gilt für alle Lehrkräfte; eigene Schlüssel legen Lehrkräfte ab Stufe D selbst an (gekennzeichnet).' }),
      G.bildungsgaenge.length ? null : el('div', { class: 'banner warnung', text: 'Zuerst unter Grunddaten einen Bildungsgang anlegen.' }),
      el('div', { class: 'zwei-spalten' }, G.bildungsgaenge.map(b => {
        const s = konf.find(x => x.bildungsgang_id === b.id);
        return el('div', { class: 'karte stapel' },
          el('div', { class: 'zeile' }, L.symbol('schloss'), el('h2', { text: b.name }),
            el('span', { class: 'rechts' }, s ? el('span', { class: 'chip', text: SYSTEMNAME[s.system] }) : el('span', { class: 'chip gelb', text: 'fehlt' }))),
          s ? [el('p', { class: 'klein' }, el('b', { text: s.name }), el('span', { class: 'leise', text: ' · geändert ' + L.wann(s.geaendert) })), band(s.system, s.grenzen)]
            : el('p', { class: 'leise klein', text: 'Noch kein Konferenzschlüssel. Prüfungen dieser Klassen lassen sich erst abschließen, wenn er eingetragen ist.' }),
          el('div', {}, el('button', { type: 'button', class: s ? 'klein' : 'haupt klein', onclick: () => schluesselBearbeiten(b, s) },
            L.symbol(s ? 'stift' : 'plus'), s ? 'bearbeiten' : 'eintragen')));
      })));
  }

  const BANDFARBEN = ['#00639C', '#5aa9d6', '#9fb400', '#F8B442', '#e2668f', '#D4005E'];

  // Farbiges Band 0–100 %: Breite je ganzer Note aus den Grenzen
  function band(system, grenzen) {
    const ganze = {};
    Object.entries(grenzen).forEach(([stufe, ab]) => {
      const g = system === 'punkte' ? (Number(stufe) >= 13 ? 1 : Number(stufe) >= 10 ? 2 : Number(stufe) >= 7 ? 3 : Number(stufe) >= 4 ? 4 : Number(stufe) >= 1 ? 5 : 6) : Number(stufe[0]);
      ganze[g] = Math.min(ganze[g] === undefined ? 101 : ganze[g], ab);
    });
    const teile = [];
    let oben = 101;
    for (let g = 1; g <= 6; g++) {
      if (ganze[g] === undefined) continue;
      teile.push(el('span', { style: 'flex:' + Math.max(oben - ganze[g], 1) + ';background:' + BANDFARBEN[g - 1] + (g === 3 || g === 4 ? ';color:#1d2433' : ''), text: String(g) }));
      oben = ganze[g];
    }
    return el('div', { class: 'notenband', 'aria-label': 'Notenbänder von 100 bis 0 Prozent' }, teile);
  }

  // b: Bildungsgang (Konferenzschluessel) oder null mit eigen: true (eigener Schluessel einer Lehrkraft)
  async function schluesselBearbeiten(b, s, optionen = {}) {
    const eigen = !!optionen.eigen;
    const danach = optionen.danach || noten;
    const name = el('input', { value: s ? s.name : (eigen ? 'Mein Notenschlüssel' : 'Konferenzschlüssel ' + (b.kuerzel || b.name)), maxlength: 60 });
    const system = el('select', {}, Object.entries(SYSTEMNAME).map(([w, t]) => el('option', { value: w, text: t, selected: s && s.system === w ? true : null })));
    const tabelleOrt = el('div', { class: 'rollbar' });
    const bandOrt = el('div');
    const pruefung = el('div', { class: 'klein' });
    let felder = {};
    let stufen = [];
    const lesen = () => Object.fromEntries(stufen.map(st => [st, felder[st].value === '' ? null : Number(felder[st].value)]));
    const pruefen = () => {
      const g = lesen();
      let fehler = '';
      stufen.forEach((st, i) => {
        if (fehler) return;
        if (g[st] === null || isNaN(g[st])) fehler = 'Bei ' + zeigeNote(st) + ' fehlt die Grenze.';
        else if (i > 0 && g[st] >= g[stufen[i - 1]]) fehler = zeigeNote(st) + ' muss unter ' + zeigeNote(stufen[i - 1]) + ' beginnen.';
      });
      if (!fehler && g[stufen[stufen.length - 1]] !== 0) fehler = 'Die schlechteste Note muss bei 0 % beginnen.';
      stufen.forEach((st, i) => { felder[st].closest('td').nextSibling.textContent = i === 0 ? '100' : (g[stufen[i - 1]] !== null ? g[stufen[i - 1]] - 1 : ''); });
      L.setzen(pruefung, fehler ? el('span', { class: 'chip rot' }, L.symbol('warnung'), fehler) : el('span', { class: 'chip gruen' }, L.symbol('ok'), 'lückenlos und absteigend'));
      L.setzen(bandOrt, fehler ? null : band(system.value, g));
    };
    const aufbauen = (grenzen, liste) => {
      stufen = liste;
      felder = {};
      const spalten = system.value === 'tendenz' ? 3 : system.value === 'punkte' ? 4 : 2;
      const proSpalte = Math.ceil(stufen.length / spalten);
      const zeilen = [];
      for (let r = 0; r < proSpalte; r++) {
        const tds = [];
        for (let c = 0; c < spalten; c++) {
          const st = stufen[c * proSpalte + r];
          if (!st) { tds.push(el('td'), el('td'), el('td')); continue; }
          felder[st] = el('input', { type: 'number', min: 0, max: 100, value: grenzen[st], 'aria-label': 'Note ' + zeigeNote(st) + ' ab Prozent', oninput: pruefen });
          tds.push(el('td', {}, el('b', { text: system.value === 'punkte' ? st + ' P' : zeigeNote(st) })), el('td', {}, felder[st]), el('td', { class: 'bis mono' }));
        }
        zeilen.push(el('tr', {}, tds));
      }
      const kopfzeile = [];
      for (let c = 0; c < spalten; c++) kopfzeile.push(el('th', { text: 'Note' }), el('th', { text: 'ab %' }), el('th', { text: 'bis %' }));
      L.setzen(tabelleOrt, el('table', { class: 'grenzen' }, el('thead', {}, el('tr', {}, kopfzeile)), el('tbody', {}, zeilen)));
      pruefen();
    };
    system.addEventListener('change', async () => {
      const v = await L.api('GET', '/api/notenschluessel/vorgabe?system=' + system.value);
      aufbauen(v.grenzen, v.stufen);
    });
    const start = s ? { grenzen: s.grenzen, stufen: s.stufen } : await L.api('GET', '/api/notenschluessel/vorgabe?system=' + system.value);
    aufbauen(start.grenzen, start.stufen);
    const r = await L.dialog({
      titel: eigen ? (s ? s.name : 'Eigener Notenschlüssel') : 'Konferenzschlüssel · ' + b.name, breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('div', { class: 'felder zwei' }, L.feld('Name', name), L.feld('Notensystem', system)),
        el('p', { class: 'leise klein', text: 'Du trägst je Note nur „ab %“ ein; „bis %“ ergibt sich. ' + (eigen ? 'Eigene Schlüssel stehen in Prüfungen als „abweichender Schlüssel“.' : 'Vorbelegt sind die Werte aus dem alten Lehrerkalender – bitte auf den Konferenzbeschluss anpassen.') }),
        el('p', { class: 'leise klein', text: 'Bei Zehntelnoten trägst du die Grenzen der ganzen Noten ein, die Zehntel werden dazwischen gleichmäßig verteilt.' }),
        pruefung, bandOrt, tabelleOrt,
        s ? L.nebenknopf('Schlüssel löschen …', async () => {
          const ok = await L.dialog({ titel: (eigen ? 'Notenschlüssel' : 'Konferenzschlüssel') + ' löschen?', knopf: 'Löschen', gefaehrlich: true,
            inhalt: el('p', { text: eigen ? 'Prüfungen, die ihn gewählt haben, nutzen danach wieder den automatischen Schlüssel; abgeschlossene bleiben unverändert.' : 'Klassen dieses Bildungsgangs haben danach keinen Schlüssel mehr.' }),
            speichern: () => L.api('POST', '/api/notenschluessel/' + s.id + '/loeschen', {}) });
          if (ok) danach();
        }) : null),
      speichern: () => L.api('POST', s ? '/api/notenschluessel/' + s.id : '/api/notenschluessel',
        { name: name.value, art: eigen ? 'eigen' : 'konferenz', bildungsgang_id: b ? b.id : null, system: system.value, grenzen: lesen() }),
    });
    if (r) { L.meldung('Gespeichert.'); danach(); }
  }

  // --- System: Update, Sicherung, VPN (vpn.js), Protokoll ---

  async function system() {
    const [u, p, kol] = await Promise.all([L.api('GET', '/api/admin/update'), L.api('GET', '/api/admin/protokoll'), L.api('GET', '/api/admin/kollegium')]);
    const pruefung = u.pruefung || {};
    L.setzen(ort,
      kopf('System'),
      el('div', { class: 'zwei-spalten' },
        el('div', { class: 'karte stapel' },
          el('h2', { text: 'Version und Update' }),
          el('p', {}, 'Installiert: ', el('b', { text: u.version }),
            pruefung.verfuegbar && pruefung.neu ? el('span', { class: 'chip gelb', style: 'margin-left:8px', text: 'neu: ' + (pruefung.verfuegbar.version || pruefung.verfuegbar.stand) }) : null),
          u.eingerichtet ? el('div', { class: 'zeile' },
            el('button', { type: 'button', onclick: () => updateAnfordern('pruefen') }, L.symbol('refresh'), 'Jetzt prüfen'),
            el('button', { type: 'button', class: 'haupt', disabled: !pruefung.neu || u.laeuft, onclick: () => updateAnfordern('ausfuehren') }, 'Jetzt aktualisieren'))
            : el('p', { class: 'leise klein', text: 'Update über die Seite geht nur im Container.' }),
          u.laeuft ? el('div', { class: 'banner', text: 'Update läuft …' }) : null,
          u.protokoll ? el('details', {}, el('summary', { text: 'Protokoll des letzten Updates' }), el('pre', { class: 'mono klein', style: 'white-space:pre-wrap', text: u.protokoll })) : null),
        el('div', { class: 'karte stapel' },
          el('h2', { text: 'Sicherung' }),
          el('p', { class: 'leise klein', text: 'Die ganze Datenbank als ZIP. Vor jedem Update legt der Container zusätzlich selbst eine Sicherung an (die letzten fünf bleiben). Dazu kommt die Proxmox-Sicherung.' }),
          el('div', {}, el('button', { type: 'button', onclick: () => L.herunterladen('/api/admin/sicherung.zip').catch(f => L.meldung(f.message, true)) }, L.symbol('laden'), 'Sicherung herunterladen')),
          einspielenTeil(),
          u.sicherungen.length ? el('div', { class: 'stapel', style: 'gap:4px' }, u.sicherungen.map(s =>
            el('a', { href: '/api/admin/update/sicherung/' + s.name, class: 'klein', text: s.name + ' (' + Math.round(s.groesse / 1024) + ' KB)' }))) : null)),
      Vpn.karte(),
      kollegiumKarte(kol),
      el('div', { class: 'karte stapel' },
        el('h2', { text: 'Änderungsprotokoll' }),
        p.protokoll.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' }, el('tbody', {}, p.protokoll.map(z => el('tr', {},
          el('td', { class: 'mono klein', text: L.wann(z.zeit) }), el('td', { class: 'mono', text: z.wer }),
          el('td', { text: z.art.replace(/_/g, ' ') }),
          el('td', { class: 'leise klein', text: Object.entries(z.daten).filter(([, v]) => v !== null && v !== undefined && v !== '')
            .map(([k, v]) => k + ': ' + (Array.isArray(v) ? v.join(', ') : v)).join(' · ') }))))))
          : el('p', { class: 'leise', text: 'Noch keine Änderungen.' })));
  }

  // --- Teilen im Kollegium (Stufe E), siehe app/kollegium.py: Vorgabe aus, erst nach Freigabe einschalten ---
  function kollegiumKarte(k) {
    const umschalten = async () => {
      if (!k.an) {
        const ja = await L.dialog({ titel: 'Teilen im Kollegium einschalten?', knopf: 'Einschalten',
          inhalt: el('div', { class: 'stapel', style: 'gap:8px' },
            el('p', { text: 'Lehrkräfte, die dieselbe Klasse laut Stundenplan unterrichten, sehen dann gegenseitig ihre Themenplanung dieser Klasse (nur lesen) und die Termine, die sie ausdrücklich für die Klasse teilen.' }),
            el('p', { text: 'Schülerlisten, Noten, Notizen, Merker, private Termine und Unterrichtsbesuche bleiben privat.' }),
            el('p', { class: 'leise klein', text: 'Bitte erst einschalten, wenn Schulleitung und Datenschutzbeauftragter zugestimmt haben.' })),
          speichern: () => true });
        if (!ja) return;
      }
      try { await L.api('POST', '/api/admin/kollegium', { an: !k.an }); L.meldung(k.an ? 'Teilen ausgeschaltet.' : 'Teilen eingeschaltet.'); system(); }
      catch (e) { L.meldung(e.message, true); }
    };
    return el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, el('h2', { text: 'Teilen im Kollegium' }),
        el('span', { class: 'chip ' + (k.an ? 'gruen' : ''), text: k.an ? 'an' : 'aus' })),
      el('p', { class: 'leise klein', text: 'Gleiche Klasse = Themenplanung lesen und geteilte Klassentermine sehen. Alles andere bleibt privat.' }),
      k.klassen.length ? el('div', { class: 'stapel', style: 'gap:4px' }, el('b', { class: 'klein', text: 'Klassen mit mehreren Lehrkräften' }),
        k.klassen.map(x => el('div', { class: 'klein' }, el('b', { text: x.klasse + ': ' }), x.lehrkraefte.join(', '))))
        : el('p', { class: 'leise klein', text: 'Noch keine Klasse steht im Stundenplan mehrerer Lehrkräfte.' }),
      el('div', {}, el('button', { type: 'button', class: k.an ? '' : 'haupt', onclick: umschalten }, k.an ? 'Ausschalten' : 'Einschalten …')));
  }

  // --- Sicherung einspielen (z. B. Testinstanz -> Produktivsystem), siehe app/wiederherstellung.py ---
  // Hochladen und pruefen macht der Webdienst, das Einspielen root ueber systemd (Dienst stoppt kurz). Danach sind alle
  // Anmeldungen beendet: die Seite fuehrt zur Anmeldung.
  function einspielenTeil() {
    const ort = el('div', { class: 'stapel', style: 'gap:8px;border-top:1px solid var(--linie);padding-top:12px' });
    const datei = el('input', { type: 'file', accept: '.zip,.sqlite,application/zip', hidden: true });
    let timer = null, beobachten = false;
    const weiter = () => { clearTimeout(timer); timer = setTimeout(() => { if (ort.isConnected) laden(); }, 2500); };

    datei.addEventListener('change', async () => {
      const d = datei.files[0];
      datei.value = '';
      if (!d) return;
      L.setzen(ort, el('div', { class: 'banner', text: 'Lädt „' + d.name + '“ hoch und prüft die Sicherung …' }));
      let antwort, inhalt = {};
      try {
        antwort = await fetch('/api/admin/wiederherstellung/hochladen', { method: 'POST', credentials: 'same-origin',
          headers: { 'X-Lehrerkalender': '1', 'Content-Type': 'application/octet-stream' }, body: d });
        try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
      } catch (e) { inhalt = { fehler: 'Keine Verbindung zum Server.' }; }
      if (!antwort || !antwort.ok) { L.meldung(inhalt.fehler || 'Hochladen fehlgeschlagen.', true); laden(); return; }
      zeichnen(inhalt);
      einspielen(inhalt.hochgeladen);
    });

    const zahl = w => (w === null || w === undefined ? '–' : String(w));
    const angaben = h => el('dl', { class: 'vpn-daten klein' },
      el('dt', { text: 'Letzte Änderung' }), el('dd', { text: h.letzte_aenderung ? L.wann(h.letzte_aenderung) : '–' }),
      el('dt', { text: 'Schule' }), el('dd', { text: h.schule || '–' }),
      el('dt', { text: 'Konten' }), el('dd', { text: zahl(h.konten) + ' (Admins: ' + h.admins.join(', ') + ')' }),
      el('dt', { text: 'Klassen' }), el('dd', { text: zahl(h.klassen) }),
      el('dt', { text: 'Prüfungen' }), el('dd', { text: zahl(h.pruefungen) }),
      el('dt', { text: 'Unterrichtsbesuche' }), el('dd', { text: zahl(h.besuche) }),
      el('dt', { text: 'Datenbankstand' }), el('dd', { text: h.stand + (h.stand < h.aktueller_stand ? ' (wird beim Einspielen auf ' + h.aktueller_stand + ' gebracht)' : '') }));

    async function einspielen(h) {
      const pw = el('input', { type: 'password', required: true, autocomplete: 'current-password' });
      const ok = el('input', { type: 'checkbox', required: true });
      const r = await L.dialog({
        titel: 'Sicherung einspielen?', knopf: 'Alle Daten ersetzen', gefaehrlich: true,
        inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
          el('p', { text: 'In der Sicherung steht:' }), angaben(h),
          el('div', { class: 'banner warnung klein', text: 'Alle Daten dieses Lehrerkalenders werden durch die Sicherung ersetzt: Konten, Stundenpläne, Planung, ' +
            'Prüfungen und Noten, Formulare, Unterrichtsbesuche. Vorher legt der Container eine Sicherung des jetzigen Stands an. ' +
            'Die Seite ist etwa eine Minute weg, danach melden sich alle neu an – mit den Passwörtern aus der Sicherung.' }),
          el('p', { class: 'leise klein', text: 'Bleibt, wie es ist: das Zertifikat (Stammzertifikat auf den Geräten) und das VPN. ' +
            'Kalender-Abos zeigen danach auf diese Adresse: Abo-Links aus der anderen Instanz in Outlook bzw. auf dem Handy neu eintragen.' }),
          el('label', { class: 'haken' }, ok, 'Ich weiß, dass alle Daten ersetzt werden.'),
          L.feld('Dein Passwort zur Bestätigung', pw)),
        speichern: () => {
          if (!ok.checked) throw new Error('Bitte bestätigen, dass alle Daten ersetzt werden.');
          return L.api('POST', '/api/admin/wiederherstellung/einspielen', { passwort: pw.value, pruefsumme: h.pruefsumme });
        },
      });
      if (r) { beobachten = true; zeichnen(r); weiter(); }
    }

    async function verwerfen() {
      try { zeichnen(await L.api('POST', '/api/admin/wiederherstellung/verwerfen', {})); } catch (e) { L.meldung(e.message, true); }
    }

    async function laden() {
      let v;
      try { v = await L.api('GET', '/api/admin/wiederherstellung'); } catch (e) {
        if (e.status === 401 && beobachten) {   // eingespielt: alle Anmeldungen sind beendet
          L.setzen(ort, el('div', { class: 'banner', text: 'Sicherung eingespielt. Bitte neu anmelden …' }));
          setTimeout(() => { location.href = '/anmelden'; }, 1500);
          return;
        }
        if (beobachten) {   // Dienst startet gerade neu
          L.setzen(ort, el('div', { class: 'banner', text: 'Die Sicherung wird eingespielt, der Dienst startet neu …' }));
          weiter();
          return;
        }
        L.setzen(ort, el('p', { class: 'leise klein', text: e.message }));
        return;
      }
      if (v.laeuft || v.wartet) beobachten = true;
      else if (beobachten && v.lauf && v.lauf.ende) {
        beobachten = false;
        L.meldung(v.lauf.ergebnis === 'ok' ? 'Sicherung eingespielt.' : 'Das Einspielen hat nicht geklappt. Details unten im Protokoll.', v.lauf.ergebnis !== 'ok');
      }
      zeichnen(v);
      if (v.laeuft || v.wartet) weiter();
    }

    function zeichnen(v) {
      const laeuft = v.laeuft || v.wartet, h = v.hochgeladen, lauf = v.lauf && v.lauf.ende ? v.lauf : null;
      L.setzen(ort, datei,
        el('b', { text: 'Sicherung einspielen' }),
        el('p', { class: 'leise klein', text: 'Eine Sicherung aus „Sicherung herunterladen“ (ZIP) übernehmen, z. B. die Daten der Testinstanz ins ' +
          'Produktivsystem. Ersetzt alle Daten hier. Die Sicherung darf nicht aus einer neueren Version stammen.' }),
        laeuft ? el('div', { class: 'banner', text: 'Die Sicherung wird eingespielt … Danach bitte neu anmelden.' }) : null,
        !laeuft && h ? el('div', { class: 'stapel', style: 'gap:6px' },
          el('p', { class: 'klein', text: 'Bereit zum Einspielen (hochgeladen ' + L.wann(h.hochgeladen) + '):' }), angaben(h),
          el('div', { class: 'zeile' },
            el('button', { type: 'button', class: 'warnen', disabled: !v.eingerichtet, onclick: () => einspielen(h) }, 'Einspielen …'),
            el('button', { type: 'button', class: 'klein', onclick: verwerfen }, 'Verwerfen'))) : null,
        !laeuft && !h ? el('div', {}, el('button', { type: 'button', disabled: !v.eingerichtet, onclick: () => datei.click() },
          L.symbol('hoch'), 'Sicherung einspielen …')) : null,
        !v.eingerichtet ? el('p', { class: 'leise klein', text: 'Geht im Container, sobald diese Version dort installiert ist.' }) : null,
        lauf ? el('details', {}, el('summary', { class: 'klein', text: 'Letztes Einspielen: ' + L.wann(lauf.ende) + (lauf.ergebnis === 'ok' ? ' · erledigt' : ' · fehlgeschlagen') }),
          el('pre', { class: 'vpn-text mono', text: v.protokoll || '(kein Protokoll)' })) : null);
    }

    laden();
    return ort;
  }

  async function updateAnfordern(art) {
    const ok = art === 'pruefen' ? true : await L.dialog({
      titel: 'Jetzt aktualisieren?', knopf: 'Aktualisieren',
      inhalt: el('p', { text: 'Vorher wird eine Sicherung angelegt. Die Seite ist während des Updates etwa eine Minute nicht erreichbar.' }),
    });
    if (!ok) return;
    try { await L.api('POST', '/api/admin/update', { art }); L.meldung(art === 'pruefen' ? 'Prüfung läuft.' : 'Update gestartet.'); setTimeout(system, 3000); }
    catch (e) { L.meldung(e.message, true); }
  }

  return { zeigen, schluesselBearbeiten };
})();
