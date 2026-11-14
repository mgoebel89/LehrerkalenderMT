'use strict';
// Code aus der Adresse (/einladung#KAL-....) gleich eintragen
if (location.hash.length > 1) document.getElementById('code').value = decodeURIComponent(location.hash.slice(1));

document.getElementById('einladung').addEventListener('submit', async ev => {
  ev.preventDefault();
  const fehler = document.getElementById('fehler');
  const knopf = ev.target.querySelector('button');
  fehler.textContent = '';
  knopf.disabled = true;
  try {
    await L.api('POST', '/api/einladung/einloesen', {
      code: document.getElementById('code').value,
      kuerzel: document.getElementById('kuerzel').value,
      name: document.getElementById('name').value,
      passwort: document.getElementById('passwort').value,
    });
    location.href = '/app';
  } catch (e) {
    fehler.textContent = e.message;
    knopf.disabled = false;
  }
});
