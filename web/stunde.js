'use strict';
// Stunden-Overlay (Stufe C2, Voransicht B, nach WebUntis-Vorbild): alles zu einer gehaltenen Stunde auf einen Blick.
// Thema aus der Planung mit Ist-Stand (wie geplant / braucht 1 Block mehr / schon fertig, Rueckgaengig), Lehrstoff
// kopieren, Merker dieser und der naechsten Stunde, Termine des Tages; blaettern zur vorigen/naechsten Stunde der Klasse.
// Jeder Tipp wird sofort gespeichert.
const Stunde = (() => {
  const el = L.el;
  const IST = [
    ['ok', 'wie geplant', 'a-g', 'Das Thema läuft wie geplant weiter.'],
    ['mehr', 'braucht 1 Block mehr', 'a-y', 'Das Thema bekommt einen Block dazu, alles Folgende rückt nach.'],
    ['fertig', 'schon fertig', 'a-r', 'Das Thema endet mit dieser Stunde, alles Folgende rückt vor.'],
  ];

  // Oeffnet das Overlay; danach() laeuft beim Schliessen, wenn sich etwas geaendert hat
  async function oeffnen(datum, beginn, danach) {
    let S;
    try { S = await L.api('GET', '/api/stunde?datum=' + datum + '&beginn=' + encodeURIComponent(beginn)); } catch (e) { L.meldung(e.message, true); return; }
    let geaendert = false;
    let rueck = null;          // Ist-Stand vor der letzten Aenderung (fuer Rueckgaengig)
    let gespeichert = '';
    const rumpf = el('div', { class: 'ov-rumpf' });
    const kopfTitel = el('div', { class: 'titel' });
    const zurueck = el('button', { type: 'button', class: 'leicht', 'aria-label': 'Vorige Stunde der Klasse' }, L.symbol('links'));
    const vor = el('button', { type: 'button', class: 'leicht', 'aria-label': 'Nächste Stunde der Klasse' }, L.symbol('rechts'));

    const laden = async (d, b) => {
      try { S = await L.api('GET', '/api/stunde?datum=' + d + '&beginn=' + encodeURIComponent(b)); rueck = null; gespeichert = ''; zeichnen(); }
      catch (e) { L.meldung(e.message, true); }
    };
    zurueck.addEventListener('click', () => S.vorige && laden(S.vorige.datum, S.vorige.beginn));
    vor.addEventListener('click', () => S.naechste && laden(S.naechste.datum, S.naechste.beginn));

    async function istSetzen(stand) {
      const vorher = S.ist;
      const neu = S.ist === stand ? null : stand;   // erneuter Tipp nimmt zurueck
      try {
        S = await L.api('POST', '/api/ist', { datum: S.datum, beginn: S.beginn, stand: neu });
        rueck = { stand: vorher };
        geaendert = true;
        gespeichert = 'gespeichert ' + new Date().toTimeString().slice(0, 5);
        zeichnen();
      } catch (e) { L.meldung(e.message, true); }
    }

    async function rueckgaengig() {
      if (!rueck) return;
      try {
        S = await L.api('POST', '/api/ist', { datum: S.datum, beginn: S.beginn, stand: rueck.stand });
        rueck = null; geaendert = true; gespeichert = 'zurückgenommen';
        zeichnen();
      } catch (e) { L.meldung(e.message, true); }
    }

    async function merkerNeu(eingabe) {
      if (!eingabe.value.trim() || !S.naechste) return;
      try {
        await L.api('POST', '/api/termin', { art: 'merker', titel: eingabe.value, datum: S.naechste.datum, beginn: S.naechste.beginn, klasse_id: S.klasse.id });
        geaendert = true;
        await laden(S.datum, S.beginn);
        gespeichert = 'Merker gespeichert';
        zeichnen();
      } catch (e) { L.meldung(e.message, true); }
    }

    async function merkerWeg(m) {
      try { await L.api('POST', '/api/termin/' + m.id + '/loeschen', {}); geaendert = true; await laden(S.datum, S.beginn); } catch (e) { L.meldung(e.message, true); }
    }

    function kopieren() {
      const t = S.thema;
      const text = t.titel + (t.hinweis ? '\n' + t.hinweis : '');
      navigator.clipboard.writeText(text).then(() => L.meldung('Lehrstoff in der Zwischenablage, jetzt in WebUntis einfügen.'),
        () => L.meldung('Kopieren ging nicht. Bitte den Text markieren und kopieren.', true));
    }

    const info = () => ({ datum: S.datum, beginn: S.beginn, ende: S.ende, name: S.klasse.name + (S.gruppe ? ' · ' + S.gruppe.name : '') });
    // nach einer Aenderung aus dem Overlay heraus: Overlay ist schon zu, der Aufrufer laedt neu
    const fertig = () => { if (danach) danach(); };

    function abschnitt(sym, titel, zahl, inhalt, rechts) {
      return el('section', { class: 'ov-ab' },
        el('div', { class: 'ab-kopf' }, L.symbol(sym), el('span', { text: titel }),
          zahl !== null ? el('span', { class: 'chip klein', text: String(zahl) }) : null, rechts ? el('span', { class: 'rechts' }, rechts) : null),
        el('div', { class: 'ab-inhalt' }, inhalt));
    }

    function zeichnen() {
      const z = S.zeile;
      const name = S.klasse.name + (S.gruppe ? ' · ' + S.gruppe.name : '');
      const lf = S.thema && S.thema.lernfeld ? ' · ' + S.thema.lernfeld + ' ' + S.thema.lernfeld_name : '';
      L.setzen(kopfTitel, el('b', { text: name + lf }),
        el('span', { class: 'leise klein mono', text: L.tag(S.datum, true) + ' · ' + (z && z.bezeichnung ? z.bezeichnung + ' · ' : '') + S.beginn + '–' + S.ende +
          (S.jetzt ? ' · jetzt' : S.datum === L.heute() ? ' · heute' : '') + (S.art === 'zusatz' ? ' · Zusatzstunde' : S.art === 'verschoben' ? ' · verschoben' : '') }));
      zurueck.disabled = !S.vorige;
      vor.disabled = !S.naechste;
      const teile = [];
      // Thema und Ist
      if (S.thema) {
        const t = S.thema;
        const begonnen = S.vergangen || S.jetzt;
        teile.push(abschnitt('plan', 'Thema aus der Planung', null, [
          el('div', {}, el('b', { text: t.titel }), el('span', { class: 'leise', text: ' · Block ' + t.teil + ' von ' + t.von }),
            t.ls ? el('span', { class: 'leise', text: ' · LS ' + t.ls }) : null),
          t.hinweis ? el('p', { class: 'klein hinweis-text', text: t.hinweis }) : null,
          el('div', { class: 'ampel-wahl', role: 'group', 'aria-label': 'Ist-Stand' }, IST.map(([w, text, farbe, hilfe]) =>
            el('button', { type: 'button', class: S.ist === w ? 'an' : null, title: hilfe, 'aria-pressed': S.ist === w ? 'true' : 'false',
              disabled: !begonnen, onclick: () => istSetzen(w) }, el('span', { class: 'ampel ' + farbe }), text))),
          !begonnen ? el('p', { class: 'leise klein', text: 'Den Ist-Stand bestätigst du ab Beginn der Stunde.' })
            : !S.ist ? el('p', { class: 'klein', style: 'color:#9a6400;font-weight:600', text: 'Ist noch nicht bestätigt.' }) : null,
          rueck ? el('div', {}, el('button', { type: 'button', class: 'klein', onclick: rueckgaengig }, L.symbol('undo'), 'Rückgängig')) : null,
        ], el('button', { type: 'button', class: 'klein', onclick: kopieren }, L.symbol('kopie'), 'Lehrstoff kopieren')));
      } else {
        teile.push(abschnitt('plan', 'Thema aus der Planung', null, el('p', { class: 'leise' },
          S.schuljahr ? 'Für diese Stunde ist kein Thema geplant. ' : 'Dieses Datum liegt in keinem Schuljahr. ',
          el('a', { href: '#planung', text: 'Zur Planung' }))));
      }
      // Merker
      const neuerMerker = el('input', { maxlength: 200, placeholder: 'z. B. Aufgabe 4 besprechen', 'aria-label': 'Merker für die nächste Stunde' });
      neuerMerker.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); merkerNeu(neuerMerker); } });
      teile.push(abschnitt('merker', 'Merker', S.merker.length + S.naechste_merker.length, [
        S.merker.length ? el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'für diese Stunde' }),
          S.merker.map(m => el('div', { class: 'zeile merker-zeile' }, el('span', { text: m.text }),
            el('button', { type: 'button', class: 'leicht klein rechts', title: 'erledigt, entfernen', onclick: () => merkerWeg(m) }, L.symbol('haken'))))) : null,
        S.naechste ? el('div', { class: 'stapel', style: 'gap:4px' },
          el('span', { class: 'etikett', text: 'für die nächste Stunde · ' + L.tag(S.naechste.datum) + ' ' + S.naechste.beginn + (S.naechste.thema ? ' · ' + S.naechste.thema : '') }),
          S.naechste_merker.map(m => el('div', { class: 'zeile merker-zeile' }, el('span', { text: m.text }),
            el('button', { type: 'button', class: 'leicht klein rechts', title: 'entfernen', onclick: () => merkerWeg(m) }, L.symbol('muell')))),
          el('div', { class: 'zeile', style: 'flex-wrap:nowrap' }, neuerMerker,
            el('button', { type: 'button', class: 'klein', onclick: () => merkerNeu(neuerMerker) }, L.symbol('plus'), 'Merken')))
          : el('p', { class: 'leise klein', text: 'Keine weitere Stunde dieser Klasse im Schuljahr.' }),
      ]));
      // Vertretung bzw. Aenderungen der Stunde
      if (S.vertreten) {
        teile.push(abschnitt('vertretung', 'Vertretung', null, [
          el('p', { text: 'Vertreten' + (S.vertreten.wer ? ' durch ' + S.vertreten.wer : '') + ' · übernimmt dein Thema' + (S.vertreten.grund ? ' · ' + S.vertreten.grund : '') }),
          el('p', { class: 'leise klein', text: 'Die Stunde zählt in der Planung als gehalten. Wurde die Vertretung nicht fertig, setze oben „braucht 1 Block mehr“.' }),
          el('div', {}, L.nebenknopf('Vertretung zurücknehmen …', async () => {
            if (await Aenderung.zuruecknehmen(info(), S.vertreten.aenderung_id, 'Vertretung' + (S.vertreten.wer ? ' durch ' + S.vertreten.wer : ''))) fertig();
          }, 'klein'))]));
      } else if (S.aendern) {
        teile.push(abschnitt('verschieben', 'Stunde ändern', null, el('div', { class: 'zeile' },
          L.nebenknopf('Ausfall …', async () => { if (await Aenderung.ausfall(info())) fertig(); }, 'klein'),
          L.nebenknopf('Ich werde vertreten …', async () => { if (await Aenderung.vertreten(info())) fertig(); }, 'klein'),
          L.nebenknopf('Verschieben …', async () => { if (await Aenderung.verschieben(info(), S.raster)) fertig(); }, 'klein'))));
      }
      // Termine des Tages
      teile.push(abschnitt('kalender', 'Termine an diesem Tag', S.termine.length, S.termine.length
        ? S.termine.map(t => el('div', { class: 'zeile' }, el('span', { class: 'mono leise klein', text: t.beginn || 'ganztags' }), el('span', { text: t.titel })))
        : el('p', { class: 'leise klein', text: 'Keine.' })));
      L.setzen(rumpf, teile);
      status.textContent = gespeichert;
    }

    const status = el('span', { class: 'gesp leise klein', 'aria-live': 'polite' });
    zeichnen();
    await L.dialog({
      titel: 'Stunde', knopf: 'Schließen', abbrechen: null, breit: true, fokus: false, speichern: () => true,
      inhalt: el('div', { class: 'ov stapel', style: 'gap:12px' }, el('div', { class: 'ov-kopf' }, zurueck, kopfTitel, vor), status, rumpf),
    });
    if (geaendert && danach) danach();
  }

  return { oeffnen };
})();
