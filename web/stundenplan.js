'use strict';
// Stundenplan einrichten (Stufe B, Voransicht J): Grundstundenplan von Hand mit Versionen (gelten ab einem Datum),
// A/B-Wochen, Eingabehilfen "Tag kopieren" und "Neue Version aus dieser". Zeilen nach Uhrzeit aus den Zeitrastern.
const Stundenplan = (() => {
  const el = L.el;
  const TAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr'];
  const TAGNAMEN = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag'];
  let ort = null;
  let E = null;          // Stand des Editors vom Server
  let gewaehlt = null;   // Version-ID

  async function zeigen(ortEl) {
    ort = ortEl;
    E = await L.api('GET', '/api/stundenplan');
    if (!E.versionen.some(v => v.id === gewaehlt)) gewaehlt = E.gilt_jetzt || (E.versionen.length ? E.versionen[E.versionen.length - 1].id : null);
    zeichnen();
  }

  async function schritt(url, daten) {
    E = await L.api('POST', url, daten || {});
    if (E.neu && url === '/api/stundenplan/version') gewaehlt = E.neu;   // nur neue Versionen auswaehlen, nicht neue Gruppen
    if (!E.versionen.some(v => v.id === gewaehlt)) gewaehlt = E.gilt_jetzt || (E.versionen.length ? E.versionen[0].id : null);
    return E;
  }

  const version = () => E.versionen.find(v => v.id === gewaehlt);
  const klasse = id => E.klassen.find(k => k.id === id);
  const gruppenVon = kid => E.gruppen.filter(g => g.klasse_id === Number(kid));
  const zeitraumText = k => !k ? '' : (k.beginn ? 'ab ' + L.tag(k.beginn).trim().slice(3) + ' ' : '') + (k.ende ? 'bis ' + L.tag(k.ende).trim().slice(3) : '');
  const gruppenName = gid => (E.gruppen.find(g => g.id === gid) || { name: '?' }).name;
  const farbe = id => E.farben[String(id)] || 'var(--leise)';
  const versionText = v => 'ab ' + L.tag(v.ab, true).slice(3) + (v.name ? ' · ' + v.name : '') + (v.id === E.gilt_jetzt ? ' (gilt jetzt)' : '');

  function zeichnen() {
    const teile = [];
    if (!E.klassen.some(k => k.aktiv) || !E.zeilen.length) {
      teile.push(el('div', { class: 'banner warnung', text: 'Es fehlen noch Klassen oder das Zeitraster. Beides legt der Admin unter Grunddaten und Klassen an.' }));
    }
    if (!E.versionen.length) {
      teile.push(ersteVersion());
      return L.setzen(ort, teile);
    }
    const v = version();
    const auswahl = el('select', { 'aria-label': 'Version', onchange: () => { gewaehlt = Number(auswahl.value); zeichnen(); } },
      E.versionen.map(x => el('option', { value: x.id, text: versionText(x), selected: x.id === gewaehlt ? true : null })));
    teile.push(el('div', { class: 'zeile' },
      L.feld('Version', auswahl),
      el('span', { class: 'rechts' },
        el('button', { type: 'button', onclick: () => gruppenVerwalten() }, L.symbol('klassen'), 'Gruppen'),
        el('button', { type: 'button', onclick: tagKopieren }, L.symbol('kopie'), 'Tag kopieren'),
        el('button', { type: 'button', onclick: () => versionNeu(v) }, L.symbol('plus'), 'Neue Version aus dieser'),
        el('button', { type: 'button', class: 'leicht', 'aria-label': 'Version bearbeiten', title: 'Version bearbeiten', onclick: () => versionBearbeiten(v) }, L.symbol('stift')),
        el('span', { class: 'chip', title: 'A-Woche = ' + E.a_woche + ' Kalenderwoche (legt der Admin fest)' }, L.symbol('kalender'), (E.ab_naechste ? 'Kommende Woche: ' : 'Diese Woche: ') + E.ab + '-Woche'))));
    teile.push(el('p', { class: 'leise klein', text: v.bis ? 'Gilt vom ' + L.tag(v.ab, true) + ' bis ' + L.tag(v.bis, true) + '.' : 'Gilt ab ' + L.tag(v.ab, true) + ' bis auf Weiteres.' }));
    teile.push(el('div', { class: 'rollbar' }, raster(v)));
    teile.push(el('p', { class: 'klein leise', text: 'Ein Tipp auf „+“ oder einen Eintrag: Klasse wählen, jede Woche oder je eine Klasse für A- und B-Woche. Die Zeiten kommen aus dem Zeitraster des Bildungsgangs der Klasse; Zeilen mit Kürzel (z. B. FT) gehören zu einem eigenen Raster.' }));
    L.setzen(ort, teile);
  }

  function raster(v) {
    const kopf = el('tr', {}, el('th', { class: 'z', text: 'Block' }), TAGE.map(t => el('th', { text: t })));
    const zeilen = E.zeilen.map(z => el('tr', {},
      el('td', { class: 'z' + (z.raster ? ' eigen' : '') + (z.fremd ? ' fremd' : '') },
        el('b', { text: z.bezeichnung || 'nicht im Raster' }), ' ', z.beginn + '–' + z.ende, z.raster ? el('span', { class: 'r', text: z.raster }) : null),
      TAGE.map((_, i) => {
        const hier = v.eintraege.filter(e => e.wochentag === i + 1 && e.beginn === z.beginn);
        const td = el('td', {}, el('button', { type: 'button', class: 'gp-feld' + (hier.length ? '' : ' frei'),
          'aria-label': TAGNAMEN[i] + ' ' + z.beginn + (hier.length ? ': ' + hier.map(e => (klasse(e.klasse_id) || {}).name).join(', ') : ': frei'),
          onclick: () => feldBearbeiten(v, i + 1, z, hier) },
        hier.length ? hier.map(e => el('span', { class: 'gk', style: '--kl:' + farbe(e.klasse_id) },
          (klasse(e.klasse_id) || { name: '?' }).name, e.gruppe_id ? el('span', { class: 'gr', text: gruppenName(e.gruppe_id) }) : null,
          e.lernfeld_id ? el('span', { class: 'lf', text: (E.lernfelder.find(l => l.id === e.lernfeld_id) || { nummer: '?' }).nummer }) : null,
          zeitraumText(klasse(e.klasse_id)) ? el('span', { class: 'bis', title: 'Unterrichtszeitraum der Klasse (legt der Admin fest)', text: zeitraumText(klasse(e.klasse_id)) }) : null,
          e.woche !== 'alle' ? el('span', { class: 'ab', text: e.woche }) : null)) : '+'));
        return td;
      })));
    return el('table', { class: 'gp' }, el('thead', {}, kopf), el('tbody', {}, zeilen));
  }

  function klassenAuswahl(z, gewaehlt, leerText) {
    const passend = E.klassen.filter(k => (k.aktiv && k.bloecke.includes(z.beginn + '-' + z.ende)) || k.id === gewaehlt);
    return el('select', {}, el('option', { value: '', text: leerText }),
      passend.map(k => el('option', { value: k.id, text: k.name + (k.stufe ? ' · ' + k.stufe : '') + (k.aktiv ? '' : ' (nicht aktiv)'),
        selected: k.id === gewaehlt ? true : null })));
  }

  // Klasse und Gruppe fuer einen Eintrag: die Gruppenauswahl erscheint nur, wenn die Klasse Gruppen hat
  function klasseUndGruppe(z, eintrag, beschriftung) {
    const kSel = klassenAuswahl(z, eintrag ? eintrag.klasse_id : null, '– frei –');
    const gSel = el('select', { 'aria-label': 'Gruppe' });
    const gFeld = L.feld('Gruppe', gSel);
    const lfSel = el('select', { 'aria-label': 'Lernfeld' });
    const lfFeld = L.feld('Lernfeld dieses Blocks', lfSel, 'nur bei parallelen Lernfeldern: dann fließen nur dessen Themen hierher');
    const fuellen = (gewaehlt, lfGewaehlt) => {
      const liste = kSel.value ? gruppenVon(kSel.value) : [];
      L.setzen(gSel, el('option', { value: '', text: 'ganze Klasse' }),
        liste.map(g => el('option', { value: g.id, text: g.name, selected: g.id === gewaehlt ? true : null })));
      gFeld.hidden = !liste.length;
      const k = kSel.value ? klasse(Number(kSel.value)) : null;
      const lfs = k ? E.lernfelder.filter(l => l.bildungsgang_id === k.bildungsgang_id) : [];
      L.setzen(lfSel, el('option', { value: '', text: '– alle Themen der Folge –' }),
        lfs.map(l => el('option', { value: l.id, text: l.nummer + ' ' + l.name, selected: l.id === lfGewaehlt ? true : null })));
      lfFeld.hidden = !lfs.length;
    };
    kSel.addEventListener('change', () => fuellen(null, null));
    fuellen(eintrag ? eintrag.gruppe_id : null, eintrag ? eintrag.lernfeld_id : null);
    return { teil: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld(beschriftung, kSel), gFeld), lfFeld),
      wert: woche => ({ klasse_id: kSel.value || null, gruppe_id: gSel.value || null, lernfeld_id: lfSel.value || null, woche }) };
  }

  async function feldBearbeiten(v, tag, z, hier) {
    const alle = hier.find(e => e.woche === 'alle');
    const a = hier.find(e => e.woche === 'A');
    const b = hier.find(e => e.woche === 'B');
    const jede = klasseUndGruppe(z, alle, 'Klasse');
    const selA = klasseUndGruppe(z, a, 'A-Woche');
    const selB = klasseUndGruppe(z, b, 'B-Woche');
    let modus = a || b ? 'ab' : 'alle';
    const teilAlle = jede.teil;
    const teilAB = el('div', { class: 'stapel', style: 'gap:10px' }, selA.teil, selB.teil);
    const seg = el('div', { class: 'segment', role: 'group', 'aria-label': 'Wochen' });
    const umschalten = m => {
      modus = m;
      teilAlle.hidden = m !== 'alle';
      teilAB.hidden = m !== 'ab';
      [...seg.children].forEach(x => x.classList.toggle('an', x.dataset.m === m));
    };
    seg.append(el('button', { type: 'button', 'data-m': 'alle', onclick: () => umschalten('alle') }, 'Jede Woche'),
      el('button', { type: 'button', 'data-m': 'ab', onclick: () => umschalten('ab') }, 'A/B-Woche verschieden'));
    umschalten(modus);
    const r = await L.dialog({
      titel: TAGNAMEN[tag - 1] + ' · ' + (z.bezeichnung ? z.bezeichnung + ' · ' : '') + z.beginn + '–' + z.ende,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        z.fremd ? el('div', { class: 'banner warnung', text: 'Diese Zeit steht in keinem Zeitraster mehr. Du kannst den Eintrag hier nur noch leeren.' }) : null,
        seg, teilAlle, teilAB,
        el('p', { class: 'leise klein', text: 'Zur Auswahl stehen die Klassen, deren Zeitraster diesen Block hat. Gruppen legst du oben über „Gruppen“ an; ohne Gruppe gilt der Block für die ganze Klasse.' })),
      speichern: () => schritt('/api/stundenplan/version/' + v.id + '/feld', {
        wochentag: tag, beginn: z.beginn, ende: z.ende,
        eintraege: modus === 'alle' ? [jede.wert('alle')] : [selA.wert('A'), selB.wert('B')] }),
    });
    if (r) zeichnen();
  }

  // Eigene Gruppen je Klasse (z. B. Gr. 1 / Gr. 2): nur fuer dich sichtbar, in der Planung je Gruppe ein eigener Strang
  async function gruppenVerwalten() {
    const aktive = E.klassen.filter(k => k.aktiv).sort((x, y) => x.name.localeCompare(y.name));
    if (!aktive.length) { L.meldung('Es gibt noch keine Klassen.', true); return; }
    const kSel = el('select', { 'aria-label': 'Klasse' }, aktive.map(k => el('option', { value: k.id, text: k.name })));
    const liste = el('div', { class: 'stapel', style: 'gap:6px' });
    const neuName = el('input', { maxlength: 20, placeholder: 'z. B. Gr. 1', 'aria-label': 'Name der neuen Gruppe' });
    const fehler = t => L.meldung(t, true);
    const aufrufen = async (url, daten) => { E = await L.api('POST', url, daten || {}); zeichnenListe(); };
    const zeichnenListe = () => {
      const gs = gruppenVon(kSel.value);
      L.setzen(liste, gs.length ? gs.map(g => {
        const name = el('input', { value: g.name, maxlength: 20, 'aria-label': 'Name der Gruppe', style: 'flex:1;min-width:0' });
        return el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, name,
          el('button', { type: 'button', class: 'klein', onclick: () => aufrufen('/api/gruppe/' + g.id, { name: name.value }).catch(e => fehler(e.message)) }, 'Umbenennen'),
          el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Gruppe ' + g.name + ' löschen',
            onclick: () => aufrufen('/api/gruppe/' + g.id + '/loeschen').catch(e => fehler(e.message)) }, L.symbol('muell')));
      }) : el('div', { class: 'zeile' }, el('span', { class: 'leise klein', text: 'Keine Gruppen: alle Blöcke gelten für die ganze Klasse.' }),
        el('button', { type: 'button', class: 'klein', onclick: async () => {
          try {
            await aufrufen('/api/gruppe', { klasse_id: Number(kSel.value), name: 'Gr. 1' });
            await aufrufen('/api/gruppe', { klasse_id: Number(kSel.value), name: 'Gr. 2' });
          } catch (e) { fehler(e.message); }
        } }, L.symbol('plus'), 'Gr. 1 und Gr. 2 anlegen')));
    };
    kSel.addEventListener('change', zeichnenListe);
    zeichnenListe();
    await L.dialog({
      titel: 'Gruppen', knopf: 'Fertig', abbrechen: null, speichern: () => true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('p', { class: 'leise klein', text: 'Teile eine Klasse in Gruppen, wenn du sie zu verschiedenen Zeiten getrennt unterrichtest. Die Gruppen siehst nur du. In der Planung (Stufe C) bekommt jede Gruppe einen eigenen Themenstand, die Blöcke mit der ganzen Klasse einen eigenen dazu.' }),
        L.feld('Klasse', kSel), liste,
        el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, neuName, el('button', { type: 'button', onclick: async () => {
          try { await aufrufen('/api/gruppe', { klasse_id: Number(kSel.value), name: neuName.value }); neuName.value = ''; } catch (e) { fehler(e.message); }
        } }, L.symbol('plus'), 'Anlegen'))),
    });
    zeichnen();
  }

  function montagHeute() {
    const d = new Date();
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function ersteVersion() {
    const ab = el('input', { type: 'date', value: montagHeute() });
    const name = el('input', { maxlength: 60, placeholder: 'z. B. 1. Halbjahr 2026/27' });
    return el('form', { class: 'karte stapel', style: 'max-width:560px', onsubmit: async ev => {
      ev.preventDefault();
      try { await schritt('/api/stundenplan/version', { ab: ab.value, name: name.value }); zeichnen(); } catch (e) { L.meldung(e.message, true); }
    } },
    el('h2', {}, L.symbol('spalten'), 'Stundenplan anlegen'),
    el('p', { class: 'leise klein', text: 'Dein Grundstundenplan gilt ab einem Datum. Zum Halbjahr legst du später eine neue Version aus dieser an; vergangene Wochen behalten den alten Plan.' }),
    el('div', { class: 'felder zwei' }, L.feld('Gilt ab', ab), L.feld('Name', name, 'freiwillig')),
    el('div', {}, el('button', { type: 'submit', class: 'haupt' }, L.symbol('plus'), 'Anlegen')));
  }

  async function versionNeu(v) {
    const ab = el('input', { type: 'date' });
    const name = el('input', { maxlength: 60, placeholder: 'z. B. 2. Halbjahr' });
    const r = await L.dialog({
      titel: 'Neue Version aus dieser', knopf: 'Anlegen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('p', { class: 'leise klein', text: 'Kopiert alle Einträge von „' + versionText(v) + '“. Bis zum neuen Datum gilt die alte Version weiter.' }),
        el('div', { class: 'felder zwei' }, L.feld('Gilt ab', ab), L.feld('Name', name, 'freiwillig'))),
      speichern: () => schritt('/api/stundenplan/version', { ab: ab.value, name: name.value, kopie_von: v.id }),
    });
    if (r) zeichnen();
  }

  async function versionBearbeiten(v) {
    const ab = el('input', { type: 'date', value: v.ab });
    const name = el('input', { maxlength: 60, value: v.name });
    const r = await L.dialog({
      titel: 'Version bearbeiten',
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('div', { class: 'felder zwei' }, L.feld('Gilt ab', ab), L.feld('Name', name, 'freiwillig')),
        el('div', {}, L.nebenknopf('Version löschen …', () => versionLoeschen(v)))),
      speichern: () => schritt('/api/stundenplan/version/' + v.id, { ab: ab.value, name: name.value }),
    });
    if (r) zeichnen();
  }

  async function versionLoeschen(v) {
    const r = await L.dialog({
      titel: 'Version löschen?', knopf: 'Löschen', gefaehrlich: true,
      inhalt: el('p', { text: '„' + versionText(v) + '“ mit allen Einträgen löschen? Wochen in ihrem Zeitraum zeigen danach die vorige Version (oder keinen Unterricht).' }),
      speichern: () => schritt('/api/stundenplan/version/' + v.id + '/loeschen'),
    });
    if (r) zeichnen();
  }

  async function tagKopieren() {
    const v = version();
    const tagAuswahl = w => el('select', {}, TAGNAMEN.map((t, i) => el('option', { value: i + 1, text: t, selected: i + 1 === w ? true : null })));
    const von = tagAuswahl(1);
    const nach = tagAuswahl(2);
    const r = await L.dialog({
      titel: 'Tag kopieren', knopf: 'Kopieren',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('div', { class: 'felder zwei' }, L.feld('von', von), L.feld('nach', nach)),
        el('p', { class: 'leise klein', text: 'Alle Blöcke des Zieltags werden durch die des ersten Tags ersetzt (nur in dieser Version).' })),
      speichern: () => schritt('/api/stundenplan/version/' + v.id + '/tag-kopieren', { von: Number(von.value), nach: Number(nach.value) }),
    });
    if (r) zeichnen();
  }

  return { zeigen };
})();
