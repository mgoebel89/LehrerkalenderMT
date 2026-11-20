'use strict';
// Stunden-Overlay (Stufe C2, Voransicht B, nach WebUntis-Vorbild): alles zu einer gehaltenen Stunde auf einen Blick.
// Thema aus der Planung mit Ist-Stand (wie geplant / braucht 1 Block mehr / schon fertig, Rueckgaengig), Unterrichtsinhalt
// (Text fuers Klassenbuch, in WebUntis kopieren) und eigene Notizen je Stunde, Merker dieser und der naechsten Stunde,
// Termine des Tages, Beobachtungen zu Schuelern (0.26.0); blaettern zur vorigen/naechsten Stunde der Klasse. Jeder Tipp wird sofort gespeichert, Texte kurz
// nach dem Tippen.
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
      await textSpeichern();
      try { S = await L.api('GET', '/api/stunde?datum=' + d + '&beginn=' + encodeURIComponent(b)); rueck = null; gespeichert = ''; felderBauen(); zeichnen(); }
      catch (e) { L.meldung(e.message, true); }
    };

    // --- Unterrichtsinhalt und Notizen: die Felder bleiben beim Neuzeichnen erhalten (Fokus, Getipptes). Gespeichert
    // wird kurz nach dem Tippen, beim Verlassen des Feldes, beim Blaettern und beim Schliessen ---
    let F = null, timer = null, laufend = Promise.resolve();
    let BO = null;             // Abschnitt Beobachtungen (einmal je Stunde gebaut, damit Auswahl und Getipptes bleiben)
    function felderBauen() {
      const e = S.eintrag;
      BO = Beobachtungen.stundeAbschnitt(S);
      const inhalt = el('textarea', { rows: 3, maxlength: 2000, placeholder: 'Was heute dran war – so steht es im Klassenbuch.', 'aria-label': 'Unterrichtsinhalt' });
      const notizen = el('textarea', { rows: 4, maxlength: 10000, placeholder: 'Deine Notizen zu dieser Stunde (nur für dich).', 'aria-label': 'Notizen' });
      inhalt.value = e.inhalt || S.vorschlag || '';
      notizen.value = e.notizen;
      // Stufe E: Notizen auf Wunsch fuer die anderen Lehrkraefte der Klasse sichtbar (nur bei eingeschaltetem Teilen)
      const geteilt = S.kollegium && S.kollegium.length ? el('input', { type: 'checkbox', checked: e.notizen_geteilt ? true : null }) : null;
      F = { inhalt, notizen, geteilt, stand: { inhalt: e.inhalt, notizen: e.notizen, geteilt: e.notizen_geteilt } };
      if (geteilt) geteilt.addEventListener('change', () => textSpeichern());
      for (const t of [inhalt, notizen]) {
        t.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(textSpeichern, 900); status.textContent = ''; });
        t.addEventListener('blur', () => textSpeichern());
      }
    }
    function textSpeichern() {
      clearTimeout(timer);
      if (!F) return laufend;
      const f = F, neu = { inhalt: f.inhalt.value.trim(), notizen: f.notizen.value.trim() };
      // ein unveraenderter Pruefungs-Vorschlag wird erst gespeichert, wenn er geaendert oder kopiert wird
      const inhaltNeu = neu.inhalt === (S.vorschlag || '') && !f.stand.inhalt && !f.kopiert ? '' : neu.inhalt;
      const geteiltNeu = f.geteilt ? f.geteilt.checked : f.stand.geteilt;
      if (inhaltNeu === f.stand.inhalt && neu.notizen === f.stand.notizen &&
          (geteiltNeu === f.stand.geteilt || (!inhaltNeu && !neu.notizen))) return laufend;
      const ort = { datum: S.datum, beginn: S.beginn };
      if (f.geteilt) ort.notizen_geteilt = geteiltNeu;
      laufend = laufend.then(async () => {
        try {
          const r = await L.api('POST', '/api/stunde/eintrag', Object.assign({}, ort, { inhalt: inhaltNeu, notizen: neu.notizen }));
          f.stand = { inhalt: r.eintrag.inhalt, notizen: r.eintrag.notizen, geteilt: r.eintrag.notizen_geteilt };
          if (F === f) { S.eintrag = r.eintrag; status.textContent = 'gespeichert ' + new Date().toTimeString().slice(0, 5); }
        } catch (e) { L.meldung(e.message, true); }
      });
      return laufend;
    }
    function uebernehmen(text) {
      const t = F.inhalt;
      const alt = t.value.trim();
      t.value = !alt || alt === (S.vorschlag || '') ? text : alt + '\n' + text;
      t.focus();
      textSpeichern();
    }
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
      const text = F.inhalt.value.trim();
      if (!text) { L.meldung('Bitte zuerst den Unterrichtsinhalt eintragen.', true); F.inhalt.focus(); return; }
      F.kopiert = true;
      textSpeichern();
      navigator.clipboard.writeText(text).then(() => L.meldung('Unterrichtsinhalt in der Zwischenablage, jetzt in WebUntis einfügen.'),
        () => { F.inhalt.select(); L.meldung('Kopieren ging nicht. Der Text ist markiert: Strg+C drücken.', true); });
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
            t.ls ? el('span', { class: 'leise', text: ' · LS ' + t.ls + (t.ls_von > 1 ? ' (' + t.ls_teil + '/' + t.ls_von + ')' : '') }) : null),
          S.geteilt && S.geteilt.length ? el('p', { class: 'leise klein', text: 'Gleicher Stoff wie bei ' + S.geteilt.join(', ') + ' am selben Tag – zusammen ein Schritt der Klasse.' }) : null,
          S.nachholen && S.nachholen.length ? el('div', { class: 'banner warnung klein' }, S.nachholen.map(n =>
            el('div', { text: n.gruppe + ' fehlte am ' + L.tag(n.datum, true) + ' – holt nach: ' + n.thema + (n.ls ? ' · ' + n.ls : '') }))) : null,
          t.hinweis ? el('p', { class: 'klein hinweis-text', text: t.hinweis }) : null,
          el('div', { class: 'ampel-wahl', role: 'group', 'aria-label': 'Ist-Stand' }, IST.map(([w, text, farbe, hilfe]) =>
            el('button', { type: 'button', class: S.ist === w ? 'an' : null, title: hilfe, 'aria-pressed': S.ist === w ? 'true' : 'false',
              disabled: !begonnen, onclick: () => istSetzen(w) }, el('span', { class: 'ampel ' + farbe }), text))),
          !begonnen ? el('p', { class: 'leise klein', text: 'Den Ist-Stand bestätigst du ab Beginn der Stunde.' })
            : !S.ist ? el('p', { class: 'klein', style: 'color:#9a6400;font-weight:600', text: 'Ist noch nicht bestätigt.' }) : null,
          rueck ? el('div', {}, el('button', { type: 'button', class: 'klein', onclick: rueckgaengig }, L.symbol('undo'), 'Rückgängig')) : null,
        ]));
      } else {
        teile.push(abschnitt('plan', 'Thema aus der Planung', null, el('p', { class: 'leise' },
          S.schuljahr ? 'Für diese Stunde ist kein Thema geplant. ' : 'Dieses Datum liegt in keinem Schuljahr. ',
          el('a', { href: '#planung', text: 'Zur Planung' }))));
      }
      // Unterrichtsinhalt (fuers Klassenbuch) und Notizen dieser Stunde
      const v = S.vorstunde;
      const vWann = v ? L.tag(v.datum) + ' ' + v.beginn + (v.gruppe ? ' · ' + v.gruppe : '') : '';
      teile.push(abschnitt('stift', 'Unterrichtsinhalt', null, [
        F.inhalt,
        el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'haupt klein', onclick: kopieren }, L.symbol('kopie'), 'In WebUntis kopieren'),
          v && v.inhalt ? el('button', { type: 'button', class: 'klein', title: 'Vorstunde ' + vWann + ': ' + v.inhalt, onclick: () => uebernehmen(v.inhalt) },
            L.symbol('rueck'), 'Aus Vorstunde übernehmen') : null,
          S.andere_gruppe.map(a => el('button', { type: 'button', class: 'klein', title: a.gruppe + ' ' + a.beginn + ': ' + a.inhalt, onclick: () => uebernehmen(a.inhalt) },
            L.symbol('rueck'), 'Von ' + a.gruppe + ' übernehmen'))),
        S.vorschlag && !S.eintrag.inhalt ? el('p', { class: 'leise klein', text: 'Vorschlag zur Prüfung: gespeichert wird er, sobald du ihn änderst oder kopierst.' }) : null,
        F.geteilt ? el('p', { class: 'leise klein' }, L.symbol('klassen'), ' Sichtbar für ' + S.kollegium.join(', ') + ' in deiner Planung (Teilen im Kollegium).') : null,
      ]));
      teile.push(abschnitt('formular', 'Notizen', null, [
        v && v.notizen ? el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'aus der Vorstunde · ' + vWann }),
          el('p', { class: 'klein hinweis-text', text: v.notizen })) : null,
        F.notizen,
        F.geteilt ? el('label', { class: 'haken' }, F.geteilt, 'Auch für ' + S.kollegium.join(', ') + ' sichtbar (z. B. für eine Vertretung)') : null,
      ]));
      // Beobachtungen zu Schuelern (privat), mehrere Schueler auf einmal
      teile.push(BO);
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
        ? S.termine.map(t => el('div', { class: 'zeile' }, el('span', { class: 'mono leise klein', text: t.beginn || 'ganztags' }), el('span', { text: t.titel }),
          t.fremd ? el('span', { class: 'leise klein', text: t.klasse + ' · von ' + t.von_name }) : t.geteilt ? L.symbol('klassen') : null))
        : el('p', { class: 'leise klein', text: 'Keine.' })));
      L.setzen(rumpf, teile);
      if (gespeichert) status.textContent = gespeichert;
    }

    const status = el('span', { class: 'gesp leise klein', 'aria-live': 'polite' });
    felderBauen();
    zeichnen();
    await L.dialog({
      titel: 'Stunde', knopf: 'Schließen', abbrechen: null, breit: true, fokus: false, speichern: () => true,
      inhalt: el('div', { class: 'ov stapel', style: 'gap:12px' }, el('div', { class: 'ov-kopf' }, zurueck, kopfTitel, vor), status, rumpf),
    });
    await textSpeichern();
    if (geaendert && danach) danach();
  }

  return { oeffnen };
})();
