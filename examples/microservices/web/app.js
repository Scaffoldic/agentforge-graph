// web — a JS frontend/BFF that calls the gateway (ENH-020 fetch capture).

async function loadHome() {
  const res = await fetch("http://gateway/");
  return res.json();
}

module.exports = { loadHome };
