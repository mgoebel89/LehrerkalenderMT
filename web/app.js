'use strict';
// Rahmen der App: Anmeldung pruefen, Seitenleiste, Bereiche ueber die Adresse (#start, #einstellungen, #admin-...).
// Start = Wochenplan (woche.js), Einstellungen = Stundenplan (stundenplan.js) und Konto (Passwort, zweiter Faktor),
// Admin (admin.js).
const el = L.el;
const inhalt = document.getElementById('inhalt');
const S = { konto: null, update: null };

const BEREICHE = Rahmen.BEREICHE;   // Bereiche der Seitenleiste: web/rahmen.js (auch fuer die Unterrichtsbesuche)

function titelSetzen(text) {
  document.getElementById('unter').textContent = text;
  L.titel(text);
}

function navigation(aktiv) {
  Rahmen.navigation(document.getElementById('navigation'), S.konto, S.update, aktiv);
}

async function zeigen() {
  if (location.hash === '#pruefungen-schueler') { location.replace('#klassen'); return; }   // fruehere Adresse der Schuelerlisten
  const ziel = (location.hash || '#start').slice(1);
  const haupt = ziel.startsWith('einstellungen') ? 'einstellungen' : ziel.startsWith('planung') ? 'planung'
    : ziel.startsWith('pruefung') ? 'pruefungen' : ziel.startsWith('klassen') ? 'klassen' : ziel;
  const bereich = BEREICHE.find(b => b.a === haupt && !b.spaeter && !b.adresse && (!b.admin || S.konto.rolle === 'admin')) || BEREICHE[0];
  navigation(bereich.a);
  L.setzen(inhalt, el('p', { class: 'leise', text: 'Lädt …' }));
  try {
    if (bereich.a === 'start') await startZeigen();
    else if (bereich.a === 'einstellungen') await einstellungenZeigen(({ 'einstellungen-konto': 'konto', 'einstellungen-kalender': 'kalender',
      'einstellungen-lernfelder': 'lernfelder' })[ziel] || 'stundenplan');
    else if (bereich.a === 'planung') await planungZeigen(ziel === 'planung-bibliothek' ? 'bibliothek' : 'planung');
    else if (bereich.a === 'klassen') await klassenZeigen(ziel);
    else if (bereich.a === 'pruefungen') await pruefungenZeigen(ziel);
    else if (bereich.a === 'formulare') { titelSetzen('Formulare'); await Formulare.zeigen(inhalt); }
    else if (bereich.a === 'dokumente') { titelSetzen('Dokumente'); await Dokumente.zeigen(inhalt); }
    else await Admin.zeigen(bereich.a, inhalt, titelSetzen);
  } catch (e) {
    if (e.status === 401) { location.href = '/anmelden'; return; }
    L.setzen(inhalt, el('div', { class: 'banner warnung', text: e.message }));
  }
}

// --- Start: Hinweisleiste und Wochenplan; fuer Admins solange die Einrichtungsliste, bis alles da ist ---

async function startZeigen() {
  titelSetzen('Start');
  const wochenOrt = el('div', { class: 'stapel', style: 'gap:12px' });
  const teile = [el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Hallo ' + S.konto.name.split(' ')[0] }),
    el('span', { class: 'leise', text: L.tag(L.heute(), true) }))];
  if (S.konto.rolle === 'admin') {
    const g = await L.api('GET', '/api/grunddaten');
    const k = await L.api('GET', '/api/admin/konten');
    const schritte = [
      ['Bildungsgänge mit Stufen angelegt', g.bildungsgaenge.length > 0 && g.bildungsgaenge.every(b => b.stufen.length), 'admin-grunddaten'],
      ['Lernfelder bzw. Module mit Stundenansatz', g.bildungsgaenge.some(b => b.lernfelder.length), 'admin-grunddaten'],
      ['Zeitraster der Schule', g.zeitraster_schule.length > 0, 'admin-grunddaten'],
      ['Schuljahr (erster und letzter Unterrichtstag)', g.schuljahre.length > 0, 'admin-grunddaten'],
      ['Ferien des Schuljahres', g.ferien.length > 0, 'admin-grunddaten'],
      ['Klassen', g.klassen.length > 0, 'admin-klassen'],
      ['Konferenz-Notenschlüssel je Bildungsgang', g.bildungsgaenge.length > 0 && g.bildungsgaenge.every(b =>
        g.notenschluessel.some(s => s.art === 'konferenz' && s.bildungsgang_id === b.id)), 'admin-noten'],
      ['Kolleginnen und Kollegen eingeladen', k.konten.length > 1 || k.einladungen.some(e => e.stand === 'offen'), 'admin-konten'],
      ['Zweiter Faktor für dein Konto', S.konto.zweiter_faktor, 'einstellungen-konto'],
    ];
    const fertig = schritte.filter(s => s[1]).length;
    if (fertig < schritte.length) {
      teile.push(el('details', { class: 'karte einrichtung' },
        el('summary', { class: 'zeile' }, el('b', { text: 'Einrichtung' }),
          el('span', { class: 'chip gelb', text: fertig + ' von ' + schritte.length }),
          el('span', { class: 'leise klein', text: 'Grunddaten für alle Lehrkräfte' })),
        el('div', { class: 'einrichtung-liste', style: 'margin-top:8px' }, schritte.map(([text, ok, ziel]) =>
          el('a', { href: '#' + ziel, class: ok ? 'ok' : null }, L.symbol(ok ? 'ok' : 'warnung'), el('span', { text }))))));
    }
  }
  const aufraeumen = el('div', { hidden: true });
  teile.push(aufraeumen, wochenOrt);
  L.setzen(inhalt, teile);
  Beobachtungen.aufraeumenHinweis().then(k => { if (k) { aufraeumen.appendChild(k); aufraeumen.hidden = false; } });   // alte Beobachtungen zu Ehemaligen
  // Ausschulungen in meinen Klassen durch Kolleginnen und Kollegen (gemeinsame Schuelerliste)
  L.api('GET', '/api/schueler/entlassungen').then(r => {
    if (!r.entlassungen.length) return;
    aufraeumen.prepend(el('div', { class: 'banner', style: 'display:grid;gap:4px;margin-bottom:8px' },
      el('div', { class: 'zeile' }, L.symbol('abmelden'), el('b', { text: 'Ausschulungen in deinen Klassen' })),
      r.entlassungen.map(e => el('div', { class: 'klein', text: e.name + ' (' + e.klasse + ') · letzter Tag ' + L.tag(e.zum, true) + (e.von ? ' · durch ' + e.von : '') }))));
    aufraeumen.hidden = false;
  }).catch(() => {});
  await Woche.zeigen(wochenOrt);
}

// --- Planung: Themenfolge und Raster je Klasse, Bibliothek ---

async function planungZeigen(reiter) {
  titelSetzen(reiter === 'bibliothek' ? 'Bibliothek' : 'Planung');
  const ort = el('div', { class: 'stapel' });
  const tab = (id, ziel, text, sym) => el('a', { class: 'knopf' + (reiter === id ? ' an' : ''), href: '#' + ziel }, L.symbol(sym), text);
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: reiter === 'bibliothek' ? 'Bibliothek' : 'Planung' }),
      el('div', { class: 'segment', role: 'group', 'aria-label': 'Planung' },
        tab('planung', 'planung', 'Planung', 'plan'), tab('bibliothek', 'planung-bibliothek', 'Bibliothek', 'pakete'))),
    ort);
  await Planung.zeigen(ort, reiter);
}

// --- Klassen: gemeinsame Schuelerliste je Klasse (mit Fotos) fuer alle Lehrkraefte der Klasse ---

// #klassen = Schuelerliste, #klassen-beobachtungen = Klassenuebersicht, #klassen-schueler-<id> = Verlauf eines Schuelers
async function klassenZeigen(ziel) {
  titelSetzen('Klassen');
  const ort = el('div', { class: 'stapel' });
  const schueler = ziel.match(/^klassen-schueler-(\d+)$/);
  if (schueler) {
    L.setzen(inhalt, ort);
    return Beobachtungen.verlaufZeigen(ort, Number(schueler[1]));
  }
  const reiter = ziel === 'klassen-beobachtungen' ? 'beobachtungen' : 'liste';
  const tab = (id, hash, text, sym) => el('a', { class: 'knopf' + (reiter === id ? ' an' : ''), href: '#' + hash }, L.symbol(sym), text);
  L.setzen(inhalt, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: reiter === 'beobachtungen' ? 'Beobachtungen' : 'Klassen' }),
    el('div', { class: 'segment', role: 'group', 'aria-label': 'Klassen' },
      tab('liste', 'klassen', 'Schülerliste', 'klassen'), tab('beobachtungen', 'klassen-beobachtungen', 'Beobachtungen', 'auge'))), ort);
  if (reiter === 'beobachtungen') await Beobachtungen.uebersichtZeigen(ort);
  else await Pruefungen.zeigen(ort, 'schueler');
}

// --- Pruefungen: Pruefungen, Vorlagen, Notenschluessel ---

async function pruefungenZeigen(ziel) {
  const reiter = ziel.startsWith('pruefung-') ? 'pruefungen' : ({ 'pruefungen-vorlagen': 'vorlagen',
    'pruefungen-schluessel': 'schluessel' })[ziel] || 'pruefungen';
  const titel = { pruefungen: 'Prüfungen', vorlagen: 'Vorlagen', schluessel: 'Notenschlüssel' }[reiter];
  titelSetzen(titel);
  const ort = el('div', { class: 'stapel' });
  const tab = (id, hash, text, sym) => el('a', { class: 'knopf' + (reiter === id ? ' an' : ''), href: '#' + hash }, L.symbol(sym), text);
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: titel }),
      el('div', { class: 'segment', role: 'group', 'aria-label': 'Prüfungen' },
        tab('pruefungen', 'pruefungen', 'Prüfungen', 'pruefung'),
        tab('vorlagen', 'pruefungen-vorlagen', 'Vorlagen', 'formular'), tab('schluessel', 'pruefungen-schluessel', 'Notenschlüssel', 'schluessel'))),
    ort);
  await Pruefungen.zeigen(ort, ziel.startsWith('pruefung-') ? ziel : reiter);
}

// --- Einstellungen: Stundenplan und Konto ---

async function einstellungenZeigen(reiter) {
  titelSetzen('Einstellungen');
  const ort = el('div', { class: 'stapel' });
  const tab = (id, ziel, text, sym) => el('a', { class: 'knopf' + (reiter === id ? ' an' : ''), href: '#' + ziel }, L.symbol(sym), text);
  const titel = { konto: 'Mein Konto', kalender: 'Kalender', lernfelder: 'Lernfelder' }[reiter] || 'Stundenplan';
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: titel }),
      el('div', { class: 'segment', role: 'group', 'aria-label': 'Einstellungen' },
        tab('stundenplan', 'einstellungen', 'Stundenplan', 'spalten'), tab('lernfelder', 'einstellungen-lernfelder', 'Lernfelder', 'pakete'),
        tab('kalender', 'einstellungen-kalender', 'Kalender', 'kalender'),
        tab('konto', 'einstellungen-konto', 'Konto und Sicherheit', 'schloss'))),
    ort);
  if (reiter === 'konto') kontoZeigen(ort);
  else if (reiter === 'kalender') L.setzen(ort, el('div', { style: 'max-width:760px' }, Abos.karte(false)));
  else if (reiter === 'lernfelder') await Lernfelder.seite(ort);
  else await Stundenplan.zeigen(ort);
}

// --- Mein Konto: Passwort und zweiter Faktor ---

function kontoZeigen(ort) {
  const k = S.konto;
  const alt = el('input', { type: 'password', autocomplete: 'current-password' });
  const neu = el('input', { type: 'password', autocomplete: 'new-password', minlength: 8 });
  L.setzen(ort,
    el('div', { class: 'zwei-spalten' },
      el('form', { class: 'karte stapel', onsubmit: async ev => {
        ev.preventDefault();
        try {
          const r = await L.api('POST', '/api/passwort', { alt: alt.value, neu: neu.value });
          S.konto = r.konto; alt.value = ''; neu.value = '';
          L.meldung('Passwort geändert. Andere Anmeldungen sind jetzt beendet.');
        } catch (e) { L.meldung(e.message, true); }
      } },
        el('h2', { text: 'Passwort' }),
        el('p', { class: 'leise klein' }, 'Angemeldet als ', el('b', { text: k.name }), ' (', el('span', { class: 'mono', text: k.kuerzel }), ', ', k.rolle === 'admin' ? 'Admin' : 'Lehrkraft', ').'),
        L.feld('Bisheriges Passwort', alt), L.feld('Neues Passwort', neu, 'mindestens 8 Zeichen'),
        el('div', {}, el('button', { class: 'haupt', type: 'submit', text: 'Passwort ändern' }))),
      el('div', { class: 'karte stapel' },
        el('div', { class: 'zeile' }, el('h2', { text: 'Zweiter Faktor' }),
          el('span', { class: 'rechts' }, el('span', { class: 'chip ' + (k.zweiter_faktor ? 'gruen' : ''), text: k.zweiter_faktor ? 'an' : 'aus' }))),
        el('p', { class: 'leise klein', text: 'Nach dem Passwort zusätzlich ein Code aus einer Authenticator-App auf deinem Handy (z. B. Microsoft oder Google Authenticator, Aegis). Freiwillig, aber empfohlen, weil hier Noten liegen.' }),
        k.zweiter_faktor
          ? el('div', { class: 'stapel', style: 'gap:8px' },
              el('p', { class: 'klein', text: 'Noch ' + k.ersatzcodes_uebrig + ' Ersatzcodes übrig.' }),
              el('div', { class: 'zeile' },
                el('button', { type: 'button', onclick: ersatzcodesErneuern }, L.symbol('refresh'), 'Neue Ersatzcodes'),
                el('button', { type: 'button', class: 'warnen', onclick: faktorAus }, 'Ausschalten')))
          : el('div', {}, el('button', { type: 'button', class: 'haupt', onclick: faktorEin }, L.symbol('schloss'), 'Einschalten'))),
      Formulare.unterschriftKarte(),
      ubKarte(),
      Dokumente.kontoKarte()));
}

// Unterrichtsbesuche (Stufe F2): je Konto einschaltbar, die Besuche sieht nur, wer sie angelegt hat
function ubKarte() {
  const an = !!S.konto.ub_an;
  return el('div', { class: 'karte stapel' },
    el('div', { class: 'zeile' }, el('h2', { text: 'Unterrichtsbesuche' }),
      el('span', { class: 'rechts' }, el('span', { class: 'chip ' + (an ? 'gruen' : ''), text: an ? 'an' : 'aus' }))),
    el('p', { class: 'leise klein', text: 'Für Fachleiter und Mentoren: Besuche bei Anwärtern vom Handy mitschreiben (Phasen, Beobachtungen, Fotos, Skizzen) und als Protokoll (PDF/ODT) ausgeben. Die Besuche sieht nur dein Konto. Ausschalten blendet den Menüpunkt aus, die Daten bleiben.' }),
    el('div', { class: 'zeile' },
      el('button', { type: 'button', class: an ? null : 'haupt', onclick: async () => {
        try {
          await L.api('POST', '/api/ub/modul', { an: !an });
          S.konto.ub_an = !an;
          zeigen();
        } catch (e) { L.meldung(e.message, true); }
      } }, an ? 'Ausschalten' : 'Einschalten'),
      an ? el('a', { class: 'knopf', href: '/unterrichtsbesuche' }, L.symbol('extern'), 'Öffnen') : null));
}

async function faktorEin() {
  let start;
  try { start = await L.api('POST', '/api/zweiter-faktor/beginnen', {}); } catch (e) { L.meldung(e.message, true); return; }
  const code = el('input', { inputmode: 'numeric', autocomplete: 'one-time-code', placeholder: '123456' });
  const r = await L.dialog({
    titel: 'Zweiten Faktor einschalten', knopf: 'Einschalten',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { class: 'klein', text: '1. Authenticator-App öffnen und diesen QR-Code scannen:' }),
      el('img', { class: 'qr-bild', alt: 'QR-Code für die Authenticator-App', src: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(start.qr) }),
      el('p', { class: 'leise klein' }, 'Ohne Kamera: Schlüssel von Hand eingeben: ', el('span', { class: 'mono', style: 'word-break:break-all', text: start.geheimnis })),
      L.feld('2. Den Code aus der App eingeben', code)),
    speichern: () => L.api('POST', '/api/zweiter-faktor/einschalten', { geheimnis: start.geheimnis, code: code.value }),
  });
  if (!r) return;
  S.konto = r.konto;
  await ersatzcodesZeigen(r.ersatzcodes);
  zeigen();
}

function ersatzcodesZeigen(codes) {
  return L.dialog({
    titel: 'Deine Ersatzcodes', knopf: 'Habe ich notiert', abbrechen: null,
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { class: 'klein', text: 'Falls dein Handy fehlt, meldest du dich mit einem dieser Codes an. Jeder gilt nur einmal. Bitte ausdrucken oder sicher notieren – sie werden nur jetzt angezeigt.' }),
      el('div', { class: 'ersatzcodes mono' }, codes.map(c => el('span', { text: c }))),
      el('div', {}, el('button', { type: 'button', onclick: () => {
        navigator.clipboard.writeText(codes.join('\n')).then(() => L.meldung('Kopiert.'), () => L.meldung('Kopieren ging nicht, bitte abschreiben.', true));
      } }, L.symbol('kopie'), 'Kopieren'))),
  });
}

async function ersatzcodesErneuern() {
  const ok = await L.dialog({ titel: 'Neue Ersatzcodes?', knopf: 'Erneuern', inhalt: el('p', { text: 'Die bisherigen Ersatzcodes gelten danach nicht mehr.' }) });
  if (!ok) return;
  try {
    const r = await L.api('POST', '/api/zweiter-faktor/ersatzcodes', {});
    S.konto = r.konto;
    await ersatzcodesZeigen(r.ersatzcodes);
    zeigen();
  } catch (e) { L.meldung(e.message, true); }
}

async function faktorAus() {
  const pw = el('input', { type: 'password', autocomplete: 'current-password' });
  const r = await L.dialog({
    titel: 'Zweiten Faktor ausschalten', knopf: 'Ausschalten', gefaehrlich: true,
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, el('p', { class: 'klein', text: 'Zur Sicherheit bitte dein Passwort eingeben.' }), L.feld('Passwort', pw)),
    speichern: () => L.api('POST', '/api/zweiter-faktor/ausschalten', { passwort: pw.value }),
  });
  if (!r) return;
  S.konto = r.konto;
  L.meldung('Zweiter Faktor ist aus.');
  zeigen();
}

// Vorlaeufiges Passwort (vom Admin gesetzt): zuerst ein eigenes festlegen
async function eigenesPasswort() {
  const alt = el('input', { type: 'password', autocomplete: 'current-password' });
  const neu = el('input', { type: 'password', autocomplete: 'new-password', minlength: 8 });
  const r = await L.dialog({
    titel: 'Eigenes Passwort festlegen', knopf: 'Speichern', abbrechen: null,
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { class: 'klein', text: 'Dein Passwort wurde vom Admin vorläufig gesetzt. Bitte jetzt ein eigenes wählen.' }),
      L.feld('Vorläufiges Passwort', alt), L.feld('Neues Passwort', neu, 'mindestens 8 Zeichen')),
    speichern: () => L.api('POST', '/api/passwort', { alt: alt.value, neu: neu.value }),
  });
  if (r) S.konto = r.konto;
}

document.getElementById('abmelden').addEventListener('click', async () => {
  try { await L.api('POST', '/api/abmelden', {}); } catch (e) { /* trotzdem weg */ }
  location.href = '/anmelden';
});

(async () => {
  try {
    const ich = await L.api('GET', '/api/ich');
    S.konto = ich.konto;
    S.update = ich.update;
    S.schule = ich.schule;
  } catch (e) {
    location.href = '/anmelden';
    return;
  }
  document.getElementById('wer').textContent = S.konto.name;
  if (S.schule && S.schule.logo) {
    const logo = document.getElementById('schul-logo');
    logo.src = '/api/schule/logo?v=' + encodeURIComponent(S.schule.stand);
    logo.alt = S.schule.name;
    logo.hidden = false;
  }
  while (S.konto.pw_vorlaeufig) await eigenesPasswort();
  window.addEventListener('hashchange', zeigen);
  zeigen();
})();
