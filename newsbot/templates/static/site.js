(function () {
  // Hide hot-linked publisher thumbnails that fail to load instead of showing broken images.
  document.querySelectorAll("img[data-hide-on-error]").forEach(function (img) {
    img.addEventListener("error", function () {
      var wrapper = img.closest(".card-media, .hero-media, .article-media");
      (wrapper || img).style.display = "none";
    });
  });

  // Client-side search over search.json.
  var input = document.getElementById("q");
  if (!input) return;
  var results = document.getElementById("search-results");
  var status = document.getElementById("search-status");
  var index = null;

  function load() {
    if (index) return Promise.resolve(index);
    return fetch(input.getAttribute("data-search-index"))
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; return data; });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render(items, q) {
    results.innerHTML = items.slice(0, 50).map(function (a) {
      return '<li><a href="' + escapeHtml(a.url) + '">' + escapeHtml(a.headline) + '</a>' +
        '<span class="meta">' + escapeHtml(a.date) + " · " + escapeHtml(a.region) + " · " +
        escapeHtml(a.category) + "</span></li>";
    }).join("");
    status.textContent = q ? items.length + " result" + (items.length === 1 ? "" : "s") + ' for "' + q + '"' : "";
  }

  var timer = null;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var q = input.value.trim().toLowerCase();
      if (!q) { results.innerHTML = ""; status.textContent = ""; return; }
      load().then(function (data) {
        var terms = q.split(/\s+/);
        var hits = data.filter(function (a) {
          var hay = [a.headline, a.standfirst, a.region, a.category, (a.tags || []).join(" "), (a.sources || []).join(" ")]
            .join(" ").toLowerCase();
          return terms.every(function (t) { return hay.indexOf(t) !== -1; });
        });
        render(hits, input.value.trim());
      });
    }, 120);
  });
})();
