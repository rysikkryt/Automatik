// Build verification only (ITLES_SELFTEST=out.png): waits for the map, saves a screenshot, reports errors.
module.exports = (win, app) => {
  const errors = [];
  win.webContents.on('console-message', (e) => {
    const level = e.level ?? e.params?.level;
    const msg = e.message ?? e.params?.message ?? '';
    if (level === 'error' || level === 3) errors.push(String(msg).slice(0, 200));
  });
  let loggedIn = false;
  win.webContents.on('did-finish-load', async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    await wait(3000);
    if (process.env.ITLES_SELFTEST_LOGIN && !loggedIn) {
      loggedIn = true;
      const js = `(() => {
        const set = (el, v) => { const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); };
        const inputs = document.querySelectorAll('form input');
        set(inputs[0], ${JSON.stringify(process.env.ITLES_SELFTEST_LOGIN)});
        set(inputs[1], ${JSON.stringify(process.env.ITLES_SELFTEST_PASSWORD || '')});
        document.querySelector('form button.btn-primary, form button[class*="btn-primary"]').click();
        return true; })()`;
      await win.webContents.executeJavaScript(js);
    }
    await wait(Number(process.env.ITLES_SELFTEST_WAIT || 8000));
    const img = await win.webContents.capturePage();
    require('fs').writeFileSync(process.env.ITLES_SELFTEST, img.toPNG());
    const url = win.webContents.getURL();
    console.log(JSON.stringify({ url, errors }));
    app.quit();
  });
};
