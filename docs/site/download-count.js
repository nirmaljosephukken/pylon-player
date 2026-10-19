/* GitHub asset downloads, across all published versions; no visitor tracking. */
(function () {
  "use strict";
  var element = document.getElementById("download-stats");
  if (!element) return;
  var api = "https://api.github.com/repos/nirmaljosephukken/pylon-player/releases";
  var key = "pylon-download-count-v1";
  var interval = 5 * 60 * 1000;
  var saved = null;
  var busy = false;

  function render(value) {
    element.textContent = value.count.toLocaleString() + " package downloads";
    element.title = "Downloads, not unique people. Counts Windows, Linux and macOS packages. " +
      "Excludes checksums and source archives. Deleted assets are not included in GitHub's current totals. " +
      "Last checked " + new Date(value.time).toLocaleString() + ".";
  }

  try {
    saved = JSON.parse(localStorage.getItem(key));
    if (!saved || !Number.isSafeInteger(saved.count) || saved.count < 0 ||
        !Number.isFinite(saved.time) || saved.time > Date.now()) saved = null;
  } catch (_) { saved = null; }
  if (saved) render(saved);

  // A page load or reload always asks GitHub. The 5-minute wait only applies
  // to the automatic refresh while the tab stays open.
  async function update(force) {
    if (busy || (!force && (document.hidden || (saved && Date.now() - saved.time < interval)))) return;
    busy = true;
    try {
      var count = 0;
      var page = 1;
      var seen = new Set();
      while (true) {
        var response = await fetch(api + "?per_page=100&page=" + page, {
          headers: {Accept: "application/vnd.github+json"},
          cache: "no-cache",
          signal: AbortSignal.timeout(15000)
        });
        if (!response.ok) throw new Error("GitHub unavailable");
        var releases = await response.json();
        if (!Array.isArray(releases)) throw new Error("Invalid release list");
        releases.forEach(function (release) {
          if (release.draft) return;
          (release.assets || []).forEach(function (asset) {
            var id = asset.id || release.tag_name + "/" + asset.name;
            if (/^Pylon.*\.(exe|appimage|zip)$/i.test(asset.name) && !seen.has(id)) {
              if (!Number.isSafeInteger(asset.download_count) || asset.download_count < 0)
                throw new Error("Invalid download count");
              seen.add(id);
              count += asset.download_count;
            }
          });
        });
        if (releases.length < 100) break;
        page += 1;
      }
      saved = {count: count, time: Date.now()};
      render(saved);
      try { localStorage.setItem(key, JSON.stringify(saved)); } catch (_) {}
    } catch (_) {
      if (saved) render(saved);
      else element.textContent = "Download count temporarily unavailable";
    } finally { busy = false; }
  }

  update(true);
  setInterval(function () { update(false); }, interval);
  document.addEventListener("visibilitychange", function () { update(false); });
})();
