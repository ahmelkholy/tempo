(async () => {
  const request = document.querySelector('meta[name="focus-mix"]');
  if (!request || window !== window.top) return;
  document.documentElement.dataset.focusConnected = "1";
  let reply;
  try {
    reply = await chrome.runtime.sendMessage(JSON.parse(request.content));
  } catch {
    reply = {error: "extension"};
  }
  try {
    const result = await fetch(location.pathname, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(reply)
    });
    if (result.ok && document.documentElement.dataset.manual === "1") {
      let message = "Your Mix reached Tempo. Return to the timer to play it.";
      if (reply?.error === "signin") {
        message = "Sign in to YouTube in this Chrome profile, then choose Connect Chrome in the timer.";
      } else if (reply?.error || !Array.isArray(reply?.tracks) || reply.tracks.length < 2) {
        message = "YouTube couldn’t confirm your personal Mix. Return to the timer for details.";
      }
      document.querySelector("p").textContent = message;
      new BroadcastChannel(location.pathname).postMessage(message);
      if (location.hash === "#approved") await chrome.runtime.sendMessage({done: true});
    } else if (result.ok) {
      await chrome.runtime.sendMessage({done: true});
    }
  } catch {
    document.querySelector("p").textContent = "The timer closed this request. You can close this tab.";
  }
})();
