'use strict';
// Anmelden in zwei Schritten: Kuerzel + Passwort; ist der zweite Faktor an, danach der Code aus der App.
let zwischen = null;

async function senden(form, fehlerId, aufruf) {
  const fehler = document.getElementById(fehlerId);
  const knopf = form.querySelector('button');
  fehler.textContent = '';
  knopf.disabled = true;
  try {
    await aufruf();
  } catch (e) {
    fehler.textContent = e.message;
    knopf.disabled = false;
  }
}

document.getElementById('anmelden').addEventListener('submit', ev => {
  ev.preventDefault();
  senden(ev.target, 'fehler', async () => {
    const r = await L.api('POST', '/api/anmelden', {
      kuerzel: document.getElementById('kuerzel').value,
      passwort: document.getElementById('passwort').value,
    });
    if (r.zweiter_faktor) {
      zwischen = r.zwischen;
      document.getElementById('anmelden').hidden = true;
      document.getElementById('code-form').hidden = false;
      document.getElementById('code').focus();
      return;
    }
    location.href = '/app';
  });
});

document.getElementById('code-form').addEventListener('submit', ev => {
  ev.preventDefault();
  senden(ev.target, 'code-fehler', async () => {
    await L.api('POST', '/api/anmelden/code', { zwischen, code: document.getElementById('code').value });
    location.href = '/app';
  });
});
