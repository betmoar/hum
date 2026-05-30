// Screenshot driver for the Hum frontend.
// Boots a headless Chromium against http://127.0.0.1:8000 and captures
// the full UI surface — desktop chrome, expanded NowPlaying overlay,
// and mobile (390×844 with bottom tab bar).

import { chromium } from 'playwright';
import fs from 'node:fs';

const BEARER = fs.readFileSync('/tmp/hum-bearer.txt', 'utf8').trim();
const BASE = 'http://127.0.0.1:8000';
const OUT = '/tmp/hum-shots';
// 1280×900 represents the typical modern desktop/laptop more honestly
// than 1280×800; the latter was on the edge of fitting full-bleed
// overlay content alongside the now-sticky controls zone.
const VIEWPORT = { width: 1280, height: 900 };
const MOBILE = { width: 390, height: 844 };
const VIDEO_ID = 'dQw4w9WgXcQ';

fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: 2,
});
await context.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());

async function shot(page, name, dpr = 2) {
  // Race document.fonts.ready against a 5s ceiling — Playwright's default
  // screenshot wrappers (page.screenshot AND locator.screenshot) wait for
  // fonts internally and can hang on the mobile context. CDP's
  // Page.captureScreenshot has no font wait. We pass an explicit `scale`
  // in the clip so the output honours deviceScaleFactor (mobile=3, desktop=2)
  // and matches the resolution of the previous captures.
  await page.evaluate(() =>
    Promise.race([
      document.fonts ? document.fonts.ready : Promise.resolve(),
      new Promise((r) => setTimeout(r, 5000)),
    ]),
  ).catch(() => {});
  const vp = page.viewportSize();
  const cdp = await page.context().newCDPSession(page);
  const { data } = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
    clip: { x: 0, y: 0, width: vp.width, height: vp.height, scale: dpr },
  });
  await cdp.detach().catch(() => {});
  fs.writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, 'base64'));
  console.log(`  saved ${name}.png`);
}
function logPage(p) {
  p.on('pageerror', (e) => console.log('  [browser ERROR]', e.message));
}

// 1. Setup
console.log('Scene 1: Setup');
let page = await context.newPage();
logPage(page);
await page.goto(BASE, { waitUntil: 'commit' });
await page.waitForSelector('input[type="password"]', { timeout: 15000 });
await page.waitForTimeout(500);
await shot(page, '01-setup');
await page.close();

await context.addInitScript((token) => localStorage.setItem('hum.bearer', token), BEARER);

// 2. Shell
console.log('Scene 2: shell');
page = await context.newPage();
logPage(page);
await page.goto(BASE + '/#/', { waitUntil: 'commit' });
await page.waitForSelector('nav', { timeout: 15000 });
await page.waitForTimeout(600);
await shot(page, '02-shell');

// 3. Search results
console.log('Scene 3: Search results');
const searchInput = await page.waitForSelector('input[type="search"]', { timeout: 10000 });
await searchInput.fill('rick astley never gonna give you up');
await searchInput.press('Enter');
try { await page.waitForSelector('button.item, .item', { timeout: 30000 }); } catch {}
await page.waitForTimeout(800);
await shot(page, '03-search-results');

// 4. Video detail
console.log('Scene 4: Video detail');
await page.goto(`${BASE}/#/video/${VIDEO_ID}`, { waitUntil: 'commit' });
try { await page.waitForSelector('button.fmt, .error', { timeout: 30000 }); } catch {}
await page.waitForTimeout(1500);
await shot(page, '04-video-detail');

// 5. Player active (shows chromatic backdrop tinting)
console.log('Scene 5: Player active (chromatic backdrop)');
const playBtn = await page.$('button.primary');
if (playBtn) {
  await playBtn.click();
  try {
    await page.waitForSelector('.player:not(.empty)', { timeout: 10000 });
    await page.waitForTimeout(3000); // backdrop crossfade + hue extract
  } catch {}
}
await shot(page, '05-player-active');

// 6. Queue
console.log('Scene 6: Queue with items');
const allButtons = await page.$$('button');
for (const b of allButtons) {
  const txt = (await b.textContent()) || '';
  if (/Add to queue/i.test(txt)) {
    await b.click(); await page.waitForTimeout(250);
    await b.click(); await page.waitForTimeout(250);
    await b.click(); await page.waitForTimeout(250);
    break;
  }
}
await page.goto(BASE + '/#/queue', { waitUntil: 'commit' });
await page.waitForSelector('section', { timeout: 5000 });
await page.waitForTimeout(900);
await shot(page, '06-queue');

// 7. Settings
console.log('Scene 7: Settings');
await page.goto(BASE + '/#/settings', { waitUntil: 'commit' });
await page.waitForSelector('section', { timeout: 5000 });
await page.waitForTimeout(600);
await shot(page, '07-settings');

// 8. Help overlay
console.log('Scene 8: Help overlay');
await page.goto(BASE + '/#/', { waitUntil: 'commit' });
await page.waitForSelector('input[type="search"]', { timeout: 5000 });
await page.click('body');
await page.keyboard.press('Shift+Slash');
await page.waitForTimeout(400);
await shot(page, '08-help-overlay');
await page.keyboard.press('Escape');
await page.waitForTimeout(300);

// 9. Confirm dialog
console.log('Scene 9: Confirm dialog');
await page.goto(BASE + '/#/queue', { waitUntil: 'commit' });
await page.waitForTimeout(700);
for (const b of await page.$$('button')) {
  const txt = (await b.textContent()) || '';
  if (/Clear all/i.test(txt)) { await b.click(); await page.waitForTimeout(400); break; }
}
await shot(page, '09-confirm-dialog');
await page.keyboard.press('Escape');
await page.waitForTimeout(300);

// 10. NEW — Expanded NowPlaying view
console.log('Scene 10: Expand-player full-bleed');
// Navigate to a video, play it, then click the mini-player art to expand.
await page.goto(`${BASE}/#/video/${VIDEO_ID}`, { waitUntil: 'commit' });
try { await page.waitForSelector('button.primary', { timeout: 15000 }); } catch {}
await (await page.$('button.primary'))?.click();
try { await page.waitForSelector('.player:not(.empty)', { timeout: 10000 }); } catch {}
await page.waitForTimeout(2500);
// The art-button in the mini-player triggers expandPlayer
const artBtn = await page.$('.art-button');
if (artBtn) {
  await artBtn.click();
  await page.waitForTimeout(1200);
}
await shot(page, '10-now-playing-expanded');
// Collapse for cleanup
await page.keyboard.press('Escape');
await page.waitForTimeout(400);

await page.close();

// 11. Mobile — Queue + tab bar at bottom
console.log('Scene 11: Mobile Queue (tab bar)');
const mobileCtx = await browser.newContext({
  viewport: MOBILE, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
});
await mobileCtx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
await mobileCtx.addInitScript((token) => {
  localStorage.setItem('hum.bearer', token);
  // Use real YouTube thumbnail URLs so the screenshot reflects production UX,
  // not the placeholder-shimmer fallback. ytimg is not blocked by the route.
  const THUMB = 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg';
  localStorage.setItem('hum.queue', JSON.stringify([
    { videoId: 'dQw4w9WgXcQ', title: 'Rick Astley - Never Gonna Give You Up', author: 'Rick Astley',
      durationSeconds: 213, thumbnailUrl: THUMB, audioUrl: '', itag: 140 },
    { videoId: 'dQw4w9WgXcQ', title: 'Rick Astley - 4K Remaster', author: 'Rick Astley',
      durationSeconds: 213, thumbnailUrl: THUMB, audioUrl: '', itag: 251 },
  ]));
  // Prime a couple of recent searches so scene 11 also implicitly demonstrates
  // the Discover empty state via the same mobile context if the user later
  // routes there. Real captures of recent-search chips would need a separate
  // scene (not added here to keep the 12-scene README structure stable).
  localStorage.setItem('hum.recent_searches', JSON.stringify([
    'rick astley',
    'lo-fi beats',
    'classical guitar',
  ]));
}, BEARER);
let mobile = await mobileCtx.newPage();
logPage(mobile);
await mobile.goto(BASE + '/#/queue', { waitUntil: 'commit' });
await mobile.waitForSelector('section', { timeout: 5000 });
await mobile.waitForTimeout(900);
await shot(mobile, '11-mobile-queue-tabbar', 3);

// 12. Mobile — Now Playing expanded
console.log('Scene 12: Mobile NowPlaying');
// Play a real track on mobile so the expanded overlay has content.
await mobile.goto(`${BASE}/#/video/${VIDEO_ID}`, { waitUntil: 'commit' });
try { await mobile.waitForSelector('button.primary', { timeout: 15000 }); } catch {}
await (await mobile.$('button.primary'))?.click();
try { await mobile.waitForSelector('.player:not(.empty)', { timeout: 10000 }); } catch {}
await mobile.waitForTimeout(2500);
const mArt = await mobile.$('.art-button');
if (mArt) {
  await mArt.click();
  await mobile.waitForTimeout(1200);
}
await shot(mobile, '12-mobile-now-playing', 3);

await mobileCtx.close();
await browser.close();
console.log('\nAll screenshots written to', OUT);
