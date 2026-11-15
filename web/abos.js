'use strict';
// Kalender-Abos (ICS-Links): eine Karte fuer die Abos der Schule (Admin: Ferien, Schultermine) bzw. die eigenen
// (z. B. Outlook). Die Karte laedt sich selbst; danach() laeuft nach Aenderungen (z. B. Ferienliste neu zeichnen).
const Abos = (() => {
  const el = L.el;

  function karte(schule, danach) {
    const ort = el('div', { class: 'karte stapel' }, el('p', { class: 'leise', text: 'Lädt …' }));
    let A = null;
    const laden = async () => {
      try { A = await L.api('GET', '/api/abos'); zeichnen(); } catch (e) { L.setzen(ort, el('div', { class: 'banner warnung', text: e.message })); }
    };
    const liste = () => (schule ? A.schule : A.eigene);

    function stand(a) {
      if (a.fehler) return el('span', { class: 'chip rot', title: a.fehler, text: 'Fehler: ' + a.fehler });
      if (!a.abgerufen) return el('span', { class: 'chip', text: 'noch nicht abgerufen' });
      return el('span', { class: 'leise klein', text: 'abgerufen ' + L.wann(a.abgerufen) + ' · ' + a.anzahl + (a.art === 'ferien' ? ' Ferienabschnitte' : ' Termine') });
    }

    async function abrufen(a, knopf) {
      knopf.disabled = true;
      try {
        const r = await L.api('POST', '/api/abo/' + a.id + '/abrufen', {});
        A = r;
        if (r.fehler) L.meldung(r.fehler, true); else L.meldung(a.name + ': ' + r.anzahl + (a.art === 'ferien' ? ' Ferienabschnitte' : ' Termine') + ' übernommen.');
        zeichnen();
        if (danach) danach();
      } catch (e) { L.meldung(e.message, true); knopf.disabled = false; }
    }

    function zeichnen() {
      const abosListe = liste();
      L.setzen(ort,
        el('div', { class: 'zeile' }, el('h2', { text: schule ? 'Kalender-Abos der Schule' : 'Meine Kalender-Abos' }),
          el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt klein', onclick: () => bearbeiten(null) }, L.symbol('plus'), 'Abo'))),
        el('p', { class: 'leise klein', text: schule
          ? 'Ein Ferien-Abo trägt die Ferien automatisch ein (ganztägige Einträge des Kalenders). Ein Termin-Abo zeigt Schultermine allen Lehrkräften im Wochenplan. Abgerufen wird alle drei Stunden.'
          : 'Termine aus deinem Kalender (z. B. Outlook) erscheinen nur für dich in der Zeile „Termine“ des Wochenplans. Abgerufen wird alle drei Stunden.' }),
        !schule && A.schule.length ? el('p', { class: 'leise klein', text: 'Von der Schule abonniert: ' + A.schule.map(a => a.name + (a.art === 'ferien' ? ' (Ferien)' : '')).join(', ') + '.' }) : null,
        abosListe.length ? el('div', { class: 'stapel', style: 'gap:8px' }, abosListe.map(a => {
          const knopf = el('button', { type: 'button', class: 'klein', onclick: () => abrufen(a, knopf) }, L.symbol('refresh'), 'Jetzt abrufen');
          return el('div', { class: 'ka' + (a.aktiv ? '' : ' aus') },
            el('div', { class: 'zeile' }, L.symbol(a.art === 'ferien' ? 'kalender' : 'extern'), el('b', { text: a.name }),
              schule ? el('span', { class: 'chip' + (a.art === 'ferien' ? ' gelb' : ' lila'), text: a.art === 'ferien' ? 'Ferien' : 'Termine' }) : null,
              a.aktiv ? null : el('span', { class: 'chip', text: 'pausiert' }),
              el('span', { class: 'rechts' }, knopf,
                el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Abo bearbeiten', onclick: () => bearbeiten(a) }, L.symbol('stift')))),
            el('div', {}, stand(a)));
        })) : el('p', { class: 'leise', text: 'Noch kein Abo.' }));
    }

    async function bearbeiten(a) {
      const name = el('input', { maxlength: 60, value: a ? a.name : '', placeholder: schule ? 'z. B. Ferien Rheinland-Pfalz' : 'z. B. Outlook dienstlich' });
      const url = el('input', { value: a ? a.url : '', placeholder: 'https://… oder webcal://…', autocomplete: 'off', spellcheck: 'false' });
      const art = el('select', {}, [['termine', 'Termine (für alle im Wochenplan)'], ['ferien', 'Ferien (trägt die Ferien ein)']].map(([w, t]) =>
        el('option', { value: w, text: t, selected: a && a.art === w ? true : null })));
      const aktiv = el('input', { type: 'checkbox', checked: !a || a.aktiv ? true : null });
      const r = await L.dialog({
        titel: a ? a.name : (schule ? 'Abo der Schule' : 'Kalender abonnieren'),
        inhalt: el('div', { class: 'felder' },
          L.feld('Name', name), L.feld('Abo-Link (ICS)', url, schule ? null : 'Outlook im Web: Einstellungen → Kalender → Freigegebene Kalender → „Kalender veröffentlichen“, „Kann alle Details anzeigen“, dann den ICS-Link kopieren.'),
          schule && !a ? L.feld('Art', art) : null,
          a ? el('label', { class: 'haken' }, aktiv, 'aktiv (regelmäßig abrufen und anzeigen)') : null,
          el('p', { class: 'leise klein', text: 'Der Link ist wie ein Schlüssel zu dem Kalender. Er bleibt im Lehrerkalender und wird nur zum Abrufen benutzt.' }),
          a ? el('div', {}, L.nebenknopf('Abo entfernen …', () => entfernen(a))) : null),
        speichern: () => L.api('POST', a ? '/api/abo/' + a.id : '/api/abo', { name: name.value, url: url.value, schule, art: art.value, aktiv: aktiv.checked }),
      });
      if (!r) return;
      A = r;
      zeichnen();
      if (!a && r.id) {   // neues Abo gleich einmal abrufen
        const neu = liste().find(x => x.id === r.id);
        if (neu) await abrufen(neu, el('button'));
      }
    }

    async function entfernen(a) {
      const r = await L.dialog({
        titel: 'Abo entfernen?', knopf: 'Entfernen', gefaehrlich: true,
        inhalt: el('p', { text: '„' + a.name + '“ und alle daraus übernommenen ' + (a.art === 'ferien' ? 'Ferien' : 'Termine') + ' verschwinden aus dem Lehrerkalender. Der Kalender selbst bleibt unverändert.' }),
        speichern: () => L.api('POST', '/api/abo/' + a.id + '/loeschen', {}),
      });
      if (r) { A = r; zeichnen(); if (danach) danach(); }
    }

    laden();
    return ort;
  }

  return { karte };
})();
