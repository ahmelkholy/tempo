// Finish setup in the profile where the user approved the extension.
chrome.runtime.onInstalled.addListener(async () => {
  try {
    const page = await fetch(chrome.runtime.getURL("connect.json"), {cache: "no-store"});
    if (!page.ok) return;
    const {url, expires} = await page.json();
    if (expires > Date.now() / 1000 && /^http:\/\/127\.0\.0\.1:\d+\/focus-mix\/[a-f0-9]{32}$/.test(url)) {
      await chrome.tabs.create({url: url + "#approved", active: false});
    }
  } catch { /* Installation also works when the timer is closed. */ }
});

// Only the paired timer receives the titles and IDs of songs in the selected Mix.
async function readMix(request) {
  const pairing = await (await fetch(chrome.runtime.getURL("pairing.json"))).json();
  if (request.pair !== pairing) return {error: "pairing"};
  const watch = new URL(request.url);
  if (watch.origin !== "https://www.youtube.com" ||
      !["/watch", "/playlist"].includes(watch.pathname) ||
      !/^RD[\w-]*$/.test(watch.searchParams.get("list") || "")) return {error: "mix"};
  return readPage(watch);
}

// Some library Mix links have no seed video. Follow YouTube's own play endpoint.
function firstMixVideo(node, mix) {
  if (!node || typeof node !== "object") return;
  const endpoint = node.watchEndpoint || node.watchPlaylistEndpoint;
  if (endpoint?.playlistId === mix && typeof endpoint.videoId === "string" &&
      /^[\w-]{11}$/.test(endpoint.videoId)) return endpoint.videoId;
  for (const child of Object.values(node)) {
    const video = firstMixVideo(child, mix);
    if (video) return video;
  }
}

async function readPage(watch) {
  const mix = watch.searchParams.get("list");
  const page = await fetch(watch.href, {
    credentials: "include", cache: "no-store", signal: AbortSignal.timeout(18000)
  });
  if (!page.ok) return {error: "network"};
  const html = await page.text();
  const initial = html.match(/\bytInitialData\s*=\s*(\{[\s\S]*?\});\s*<\/script>/);
  if (!initial) return {error: new URL(page.url).hostname === "accounts.google.com" ? "signin" : "format"};
  const data = JSON.parse(initial[1]);
  const loggedOut = data.responseContext?.mainAppWebResponseContext?.loggedOut;
  const config = html.match(/\bytcfg\.set\((\{[^\n]*?\})\);/);
  if (loggedOut !== false && (loggedOut !== undefined || !config || JSON.parse(config[1]).LOGGED_IN !== true)) {
    return {error: "signin"};
  }
  const list = data.contents?.twoColumnWatchNextResults?.playlist?.playlist;
  if (!list && watch.pathname === "/playlist") {
    const seed = firstMixVideo(data.header, mix) || firstMixVideo(data.contents, mix);
    if (seed) return readPage(new URL("https://www.youtube.com/watch?" + new URLSearchParams({v: seed, list: mix})));
  }
  if (!list || list.playlistId !== mix) return {error: "mix"};
  const rows = list.contents.map(item => item.playlistPanelVideoRenderer).filter(row => row?.videoId);
  let selected = rows.findIndex(row => row.selected);
  if (selected === -1) selected = rows.findIndex(row => row.videoId === watch.searchParams.get("v"));
  const tracks = rows.slice(Math.max(0, selected), Math.max(0, selected) + 50).map(row => ({
    id: row.videoId,
    title: (row.title?.simpleText || row.title?.runs?.map(run => run.text).join("") || "").slice(0, 300),
    link: row.navigationEndpoint?.commandMetadata?.webCommandMetadata?.url || ""
  }));
  return {mix: list.playlistId, tracks};
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!sender.tab || sender.frameId !== 0 ||
      !/^http:\/\/127\.0\.0\.1:\d+\/focus-mix\/[a-f0-9]{32}(?:#approved)?$/.test(sender.url || "")) return;
  if (message.done) {
    chrome.tabs.remove(sender.tab.id).catch(() => {});
    return;
  }
  readMix(message).then(respond, () => respond({error: "network"}));
  return true;
});
