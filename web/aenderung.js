'use strict';
// Gemeinsame Dialoge fuer einmalige Aenderungen einer regulaeren Stunde (Wochenplan und Stunden-Overlay):
// Ausfall, Ich werde vertreten (mit Pflichtwahl: Vertretung uebernimmt mein Thema / eigener Stoff), Verschieben.
// Jede Funktion bekommt die Stunde als { datum, beginn, ende, name } und liefert true, wenn etwas gespeichert wurde.
const Aenderung = (() => {
  const el = L.el;
  const GRUENDE = ['Krankheit', 'Fortbildung', 'Exkursion', 'Prüfung', 'Praktikum', 'Klassenfahrt', 'Betriebsbesichtigung', 'Konferenz'];

  function grundFeld(wert) {
    const id = 'gruende-' + Math.random().toString(36).slice(2);
    const eingabe = el('input', { list: id, value: wert || '', maxlength: 200, placeholder: 'z. B. Exkursion' });
    return [eingabe, el('datalist', { id }, GRUENDE.map(g => el('option', { value: g })))];
  }

  function stundeText(s) {
    return el('p', { class: 'klein' }, el('b', { text: s.name }), ' · ' + L.tag(s.datum, true) + ' · ' + s.beginn + (s.ende ? '–' + s.ende : ''));
  }

  async function senden(daten) {
    await L.api('POST', '/api/aenderung', daten);
    return true;
  }

  async function ausfall(s) {
    const [grund, liste] = grundFeld();
    return !!await L.dialog({
      titel: 'Stunde fällt aus', knopf: 'Ausfall eintragen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(s), L.feld('Grund', grund, 'erscheint im Wochenplan'), liste,
        el('p', { class: 'leise klein', text: 'In der Planung fällt die Stunde heraus, das Thema und alle folgenden rücken nach.' })),
      speichern: () => senden({ art: 'ausfall', datum: s.datum, beginn: s.beginn, grund: grund.value }),
    });
  }

  async function vertreten(s) {
    const wer = el('input', { maxlength: 80, placeholder: 'z. B. Kollege R.' });
    const [grund, liste] = grundFeld();
    const name = 'thema-' + Math.random().toString(36).slice(2);
    const wahl = [['ja', 'Übernimmt mein Thema', 'Die Stunde zählt in der Planung als gehalten. Den Ist-Stand kannst du danach im Overlay setzen, musst aber nicht.'],
      ['nein', 'Eigener Stoff', 'Die Stunde zählt nicht: Dein Thema wartet auf deine nächste Stunde.']];
    const knoepfe = wahl.map(([w, text, hilfe]) => el('label', { class: 'wahl-karte' },
      el('input', { type: 'radio', name, value: w }), el('span', {}, el('b', { text }), el('span', { class: 'leise klein', text: hilfe }))));
    return !!await L.dialog({
      titel: 'Ich werde vertreten', knopf: 'Eintragen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(s),
        el('p', { class: 'leise klein', text: 'Die Stunde findet für die Klasse statt, aber nicht mit dir – anders als ein Ausfall.' }),
        el('fieldset', { class: 'wahl-gruppe' }, el('legend', { text: 'Was macht die Vertretung?' }), knoepfe),
        L.feld('Wer vertritt?', wer, 'freiwillig'), L.feld('Grund', grund, 'freiwillig'), liste),
      speichern: () => {
        const gewaehlt = knoepfe.map(k => k.querySelector('input')).find(i => i.checked);
        if (!gewaehlt) throw new Error('Bitte wählen: Übernimmt die Vertretung dein Thema oder macht sie eigenen Stoff?');
        return senden({ art: 'vertreten', datum: s.datum, beginn: s.beginn, wer: wer.value, grund: grund.value, thema_weiter: gewaehlt.value === 'ja' });
      },
    });
  }

  // bloecke: [{ beginn, ende, bezeichnung }] laut Zeitraster der Klasse
  async function verschieben(s, bloecke) {
    const datum = el('input', { type: 'date', value: s.datum });
    const block = el('select', {}, bloecke.map(b => el('option', { value: b.beginn,
      text: (b.bezeichnung ? b.bezeichnung + ' · ' : '') + b.beginn + '–' + b.ende, selected: b.beginn === s.beginn ? true : null })));
    const [grund, liste] = grundFeld();
    return !!await L.dialog({
      titel: 'Stunde verschieben', knopf: 'Verschieben',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(s),
        el('div', { class: 'felder zwei' }, L.feld('Neuer Tag', datum), L.feld('Neuer Block', block)),
        L.feld('Grund', grund, 'freiwillig'), liste),
      speichern: () => senden({ art: 'verschoben', datum: s.datum, beginn: s.beginn, ziel_datum: datum.value, ziel_beginn: block.value, grund: grund.value }),
    });
  }

  async function zuruecknehmen(s, aenderungId, text) {
    return !!await L.dialog({
      titel: 'Änderung zurücknehmen?', knopf: 'Zurücknehmen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(s), text ? el('p', { text }) : null,
        el('p', { class: 'leise klein', text: 'Danach gilt wieder der Stundenplan.' })),
      speichern: () => L.api('POST', '/api/aenderung/' + aenderungId + '/loeschen', {}),
    });
  }

  return { grundFeld, ausfall, vertreten, verschieben, zuruecknehmen };
})();
