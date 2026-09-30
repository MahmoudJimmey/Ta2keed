// Appearance: auto (system) / light / dark. Loaded in <head> to avoid a flash.
(function () {
  var t = localStorage.getItem("ta2keed-theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  window.toggleTheme = function () {
    var cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("ta2keed-theme", next);
  };
})();
