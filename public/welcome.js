// Landing page. The hero's entrance and its moving lights are CSS
// (welcome.css). This does two small things:
//  - the first key, click, touch or scroll cuts the entrance short and shows
//    the finished page at once, so nobody waits for the headline;
//  - it turns on the lights that keep moving after the entrance, and gives
//    them a pause button.
(() => {
  const root = document.documentElement;
  const events = ['keydown', 'pointerdown', 'wheel', 'touchstart'];
  const skip = () => {
    root.classList.add('sky-skip');
    events.forEach((name) => removeEventListener(name, skip, true));
  };
  events.forEach((name) => addEventListener(name, skip, { capture: true, passive: true }));

  const toggle = document.querySelector('.motion');
  if (!toggle) return;
  toggle.hidden = false;
  root.classList.add('has-life');
  toggle.addEventListener('click', () => {
    const paused = root.classList.toggle('life-paused');
    toggle.setAttribute('aria-pressed', String(paused));
  });
})();
