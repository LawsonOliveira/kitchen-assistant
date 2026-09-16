// Da despensa ao cardápio: slide navigation, presenter timer and notes, the pixel Dona Sálvia, the turn stepper and
// the demo videos. Keys: → ← space PageUp/PageDown Home End · P timer + notes · R restart timer · V play/pause · F full screen
// · T cycles mid-dark → light → dark.
(() => {
  const slides = [...document.querySelectorAll(".slide")];
  const wide = matchMedia("(min-width: 760px)");
  const track = document.querySelector(".track");
  const count = document.querySelector(".count");
  const notes = document.querySelector(".notes");
  const clockTotal = document.querySelector("#clock-total");
  const clockSlide = document.querySelector("#clock-slide");
  const planned = slides.map((s) => Number(s.dataset.seconds || 0));
  const plannedTotal = planned.reduce((a, b) => a + b, 0);
  let current = Math.min(Math.max((parseInt(location.hash.slice(1), 10) || 1) - 1, 0), slides.length - 1);
  let talkStart = null;
  let slideStart = Date.now();

  const root = document.documentElement;
  const themes = ["", "light", "dark"];  // "" is the default mid-dark
  try { const saved = localStorage.getItem("deck-theme"); if (themes.includes(saved) && saved) root.dataset.deck = saved; } catch {}
  const mmss = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

  slides.forEach((slide, index) => {
    const seg = document.createElement("button");
    seg.className = "seg" + (slide.dataset.kind === "video" ? " video" : "");
    seg.style.flex = String(planned[index] || 1);
    seg.title = `${index + 1}. ${slide.dataset.title} · ${mmss(planned[index])}`;
    seg.setAttribute("aria-label", seg.title);
    seg.addEventListener("click", () => show(index));
    track.append(seg);
  });
  const segs = [...track.children];

  function show(index) {
    current = Math.min(Math.max(index, 0), slides.length - 1);
    slides.forEach((slide, k) => slide.classList.toggle("is-current", k === current));
    segs.forEach((seg, k) => {
      seg.classList.toggle("is-current", k === current);
      seg.classList.toggle("done", k < current);
    });
    count.textContent = `${current + 1} / ${slides.length}`;
    if (location.hash !== `#${current + 1}`) history.replaceState(null, "", `#${current + 1}`);
    const speaker = slides[current].querySelector(".speaker");
    notes.innerHTML = speaker ? `<b>${mmss(planned[current])}</b>${speaker.innerHTML}` : "";
    document.querySelectorAll("video").forEach((video) => { if (!slides[current].contains(video)) video.pause(); });
    slideStart = Date.now();
    tick();
  }

  function setMode() {
    document.body.classList.toggle("presenting", wide.matches);
    show(current);
  }

  function tick() {
    if (talkStart === null) return;
    const total = (Date.now() - talkStart) / 1000;
    const onSlide = (Date.now() - slideStart) / 1000;
    const budgetSoFar = planned.slice(0, current + 1).reduce((a, b) => a + b, 0);
    clockTotal.textContent = `${mmss(total)} / ${mmss(plannedTotal)}`;
    clockTotal.classList.toggle("over", total > budgetSoFar);
    clockSlide.textContent = `slide ${mmss(onSlide)} / ${mmss(planned[current])}`;
    clockSlide.classList.toggle("over", onSlide > planned[current]);
  }
  setInterval(tick, 500);

  document.addEventListener("keydown", (event) => {
    if (!document.body.classList.contains("presenting") || event.metaKey || event.ctrlKey || event.altKey) return;
    const onControl = event.target.closest("button, video, a");
    const key = event.key;
    if (key === "ArrowRight" || key === "PageDown" || (key === " " && !onControl)) { event.preventDefault(); show(current + 1); }
    else if (key === "ArrowLeft" || key === "PageUp") { event.preventDefault(); show(current - 1); }
    else if (key === "Home") show(0);
    else if (key === "End") show(slides.length - 1);
    else if (key === "p" || key === "P") {
      document.body.classList.toggle("timing");
      if (talkStart === null) { talkStart = Date.now(); slideStart = Date.now(); }
      tick();
    } else if (key === "r" || key === "R") { talkStart = Date.now(); slideStart = Date.now(); tick(); }
    else if (key === "v" || key === "V") {
      const video = slides[current].querySelector("video");
      if (video && !video.dataset.missing) video.paused ? video.play() : video.pause();
    } else if (key === "t" || key === "T") {
      const next = themes[(themes.indexOf(root.dataset.deck || "") + 1) % themes.length];
      if (next) root.dataset.deck = next; else delete root.dataset.deck;
      try { localStorage.setItem("deck-theme", next); } catch {}
    } else if (key === "f" || key === "F") {
      document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.();
    }
  });
  document.querySelectorAll(".rail .nav").forEach((button) =>
    button.addEventListener("click", () => show(current + Number(button.dataset.step))));
  wide.addEventListener("change", setMode);
  setMode();

  // --- Dona Sálvia, drawn from agents/orchestrator/dona-salvia-hero.txt (the CLI banner's own pixel art) ---------------
  const palette = { A: "#BEC2D1", B: "#7FBAD4", D: "#56617E", H: "#C8845A", K: "#2E3A59", L: "#DDE3EE", M: "#DDE2EA", O: "#F28C45",
    R: "#EE5D6C", S: "#A9ADCB", Y: "#F9B47C", d: "#9C5F3C", h: "#E3A474", m: "#9AA3B5", o: "#D9692B", r: "#FF9CA6", s: "#8B8FAF" };
  const rows = `....................KKKKKKK.KHHHHHHHK...............
.................KKKHHHHHHHKKHhhHHHHKK..............
...............KKHHHHhhHHHHHHHHHHHHHHHKK............
..............KHHHHHHHHHHHHHHHHHHHHHHHHHK...........
..............KHhhHHHHHHHHHHHHHHHHHHhHHHK...........
..............KHHHHHHHHHHHHHHHHHHHHHHHHHK...........
.............KHHHHHHHHHHHHHHHHHHHHHHHHHHK...........
.............KHHHHHHHHHHHHHHHHHHHHHHHHHHK...........
.............KHHHHHHHHHHHHHHHHHHHHHHHHHHK...........
.............KHHHHHHHHHddHHHHHHHdHHHHHHHK...........
.............KHHHHKKHHHKKKKHHHHKKKKHHHHHK...........
............KKHHHHSSKKKSSSSKKKKSSSSHHHdHK...........
...........KYKHHHHSSSSSSSSSSSSSSSSSHHHdHK...........
........KKKMKKHHHHSSSSSSSSSSSSSSSSSHHHHHKK..........
.....KKKMMMMKKHdHKKKKKKKKKSSKKKKKKKKKKKKOKKK........
....KMMMMMMMMKHdHKLLLLLLLKKKKLLLLLLLKSKKKMMMKK......
....KMMMMMmMMKHHHKLLLKKLLKSSKLLLKKLLKSKMMMKMMMK.....
..KKKKMMmMmMMKHHKKLLLLLLLKSSKLLLLLLLKKMKKMKMKKMKKK..
.KOOOKMMmMmMMKKKSKKKKKKKKKSSKKKKKKKKKKMKMKOKMKMKOOK.
KOOOOKMMmMMmMMKKSSSSSSSSSSSSSSSSSSSSKMKKMKOKMKKMKOOK
KOOOOKMMMmMmMMKKSSSSSSSSSSSSSSSSSSSSKMKKMKKKMKKMKOOK
OOOOKYKMMmMmMMKKSSSSSSSSSSSSSSSSSSSSKMKKMKKKMKKMKOOO
OOOOKYKMMmMMMMKKSSSSSSSKSSSSSSKSSSSSKMKKMK.KMKKMKOOO
OOOOKYKMMMMMMMMKSSSSSSSSKKKKKKSSSSSSKMKKMK.KMKKMKOOO
OOOKOOKMMMMMMMMKSSSSSSSSSSSSSSSSSSSSKMMKMK.KMKMMKOOO
KOOKOOOKMMMMKKK.KSSSSSSSSSSSSSSSSSSSsKMKMK.KMKMKKOOK
KOOKOOOKMKKKmmK..KSSSSKKKKKKKKKKSSSSKKMMMMKMMMMKKOOK
.KOKOOOKK..KmmK...KKKKSSSSSSSSSSKKKK..KMMMKMMMKOKOK.
..KKOOOK...KmmK...KKKKKKKKKKKKKKKKKK...KMMMMMKOOKK..
...KOOOK...KmmK..KBBKBBBBBBBBBBBBKBBK..KMMKMMKOOK...
...KOOOK...KmmK.KBBKKKKKKKKKKKKKKKKBBK..KMKMKOOOK...
...KOOOK...KmmKKKBBKAAAAAAAAAAAAAAKBBKKKKMMMKOOOK...
...KOOOOK..KKKKSSKBKAAAAAAAAAAAAAAKBKSKKKKMKOOOOK...
....KOOOK.KSSSKSKBBKAAAARRAARRAAAAKBBKSSSKMKOOOK....
....KOOOKKSSSSSKKBBKAAARrRRRRRRAAAKBKSSSSSKKOOOK....
....KOOOoKSSSSSKBBBKAAARRRRRRRRAAAKBKSSSSSKoOOOK....
.....KOOoKSSSSSKBBBKAAAARRRRRRAAAAKBKSSSSSKKOOK.....
.....KOOOKSSSSSKBBBKAAAAARRRRAAAAAKBKSSSSSKOOOK.....
......KOOOKSSSKBBBBKAAAAAARRAAAAAAKBBKSSSKOOOK......
......KKOOoKKKKBBBBKAAAAAAAAAAAAAAKBBBKKKDKOKK......
.......KOOOKDDKBBBBKAAAAAAAAAAAAAAKBBBBKDDKOK.......
........KOOKDDKBBBKAAAAAAAAAAAAAAAAKBBBKDDKK........
.........KOOOooKKBKAAAAAAAAAAAAAAAAKKooOOOK.........
..........KOOOOoKKKAAAAAAAAAAAAAAKKKoOOOOK..........
...........KOOOOooKKKKAAAAAAAAKKKKooOOOOK...........
............KKOOOOooooKKKKKKKKooooOOOOKK............
..............KKOOOOOOooooooooOOOOOOKK..............
...............KKKOOOOOOOOOOOOOOOOKKK...............
..................KKKOOOOOOOOOOKKK..................
.....................KKKKKKKKKK.....................`.split("\n");
  const hero = document.querySelector("#hero");
  if (hero) {
    const pen = hero.getContext("2d");
    rows.forEach((row, y) => [...row].forEach((pixel, x) => {
      if (palette[pixel]) { pen.fillStyle = palette[pixel]; pen.fillRect(x, y, 1, 1); }
    }));
  }

  // --- the skin's own thinking verbs ---------------------------------------------------------------------------------
  const spinner = document.querySelector("#spinner");
  if (spinner) {
    const verbs = ["mexendo a panela", "provando o tempero", "picando cebola", "fazendo as contas no caderninho"];
    const frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let step = 0;
    const draw = () => {
      spinner.innerHTML = `<b>${frames[step % frames.length]}</b> ${verbs[Math.floor(step / 24) % verbs.length]}…`;
      step += 1;
    };
    draw();
    if (!still) setInterval(draw, 100);
  }

  // --- one turn, step by step ------------------------------------------------------------------------------------------
  document.querySelectorAll(".steps").forEach((group) => {
    const figure = document.querySelector(group.dataset.for);
    const buttons = [...group.querySelectorAll(".step")];
    buttons.forEach((button) => button.addEventListener("click", () => {
      const pressed = button.getAttribute("aria-pressed") === "true";
      buttons.forEach((b) => b.setAttribute("aria-pressed", "false"));
      const active = pressed ? null : button.dataset.step;
      if (active) button.setAttribute("aria-pressed", "true");
      figure.querySelectorAll("[data-on]").forEach((el) =>
        el.classList.toggle("on", active !== null && el.dataset.on.split(" ").includes(active)));
    }));
  });

  // --- demo videos: chapters seek; a missing file says which file to record ----------------------------------------------
  document.querySelectorAll(".demo").forEach((demo) => {
    const video = demo.querySelector("video");
    const missing = demo.querySelector(".missing");
    const chapters = [...demo.querySelectorAll(".chapter")];
    const markMissing = () => { video.dataset.missing = "1"; missing.hidden = false; };
    video.addEventListener("error", markMissing);
    if (video.networkState === HTMLMediaElement.NETWORK_NO_SOURCE) markMissing();
    video.addEventListener("loadeddata", () => { delete video.dataset.missing; missing.hidden = true; });
    chapters.forEach((chapter) => chapter.addEventListener("click", () => {
      if (video.dataset.missing) return;
      video.currentTime = Number(chapter.dataset.t);
      video.play();
    }));
    video.addEventListener("timeupdate", () => {
      const now = chapters.filter((c) => Number(c.dataset.t) <= video.currentTime + 0.25).pop();
      chapters.forEach((c) => c.classList.toggle("is-now", c === now));
    });
  });

  // --- closing screenshot: a missing file says which file to drop in ------------------------------------------------------
  document.querySelectorAll(".shot").forEach((shot) => {
    const image = shot.querySelector("img");
    const missing = shot.querySelector(".missing");
    const markMissing = () => { image.hidden = true; missing.hidden = false; };
    image.addEventListener("error", markMissing);
    if (image.complete && !image.naturalWidth) markMissing();
  });
})();
