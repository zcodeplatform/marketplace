(() => {
  const fallbackSrc = document.currentScript?.dataset.fallbackSrc;
  if (!fallbackSrc) return;

  document.addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || image.dataset.imageFallbackApplied) return;

    image.dataset.imageFallbackApplied = "true";
    image.removeAttribute("srcset");
    image.src = fallbackSrc;
  }, true);
})();
