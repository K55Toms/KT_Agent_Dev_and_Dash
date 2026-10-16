'use strict';
(() => {
  const themes = {
    terminal: {
      label: '01 / Terminal Ops',
      description: 'Homebrew-inspired black and green, with Menlo / Monaco typography.',
      kicker: 'SYSTEM READY. HUMAN IN COMMAND.',
      title: 'make something matter',
      footer: 'TERMINAL OPS / KEEP BUILDING_',
      notesTitle: 'For the command-line state of mind.',
      notes: 'An almost-black canvas, green signals and amber decisions. Menlo and Monaco carry the entire interface, with square edges, explicit labels and a compact operations-console rhythm. Inspired by a terminal aesthetic; this is a dashboard, not a working shell.'
    },
    rebel: {
      label: '02 / Rebel Command',
      description: 'Navy and silver with orange-red signals and warm amber attention states.',
      kicker: 'INDEPENDENT MINDS. SHARED MISSION.',
      title: 'Build against the ordinary',
      footer: 'REBEL COMMAND / BUILD YOUR OWN WAY',
      notesTitle: 'A little louder. Still in control.',
      notes: 'Logo-matched navy and silver meet an interpreted orange-red and amber palette. Strong uppercase headlines, assertive panel edges and warm signals make this direction feel like a mission control room. These are design interpretations, not an official brand palette.'
    },
    hybrid: {
      label: '03 / Hybrid Night Shift',
      description: 'Logo-matched navy and silver with restrained green and orange.',
      kicker: 'YOUR TEAM. IN MOTION.',
      title: 'Build something that matters',
      footer: 'NIGHT SHIFT / BUILT TO KEEP GOING',
      notesTitle: 'A little terminal. A lot of clarity.',
      notes: 'Navy and silver stay close to your original logo. Clean sans-serif reading surfaces pair with monospaced technical details. Green signals activity; orange calls for human attention. A quieter, readable direction for long sessions and everyday engineering work.'
    }
  };
  const preview = document.getElementById('preview');
  const buttons = [...document.querySelectorAll('[data-theme]')];
  function selectTheme(name, announce = true) {
    const theme = themes[name];
    if (!theme) return;
    preview.className = `dashboard-preview theme-${name}`;
    preview.setAttribute('aria-label', `${theme.label.slice(5)} dashboard design preview`);
    document.getElementById('theme-label').textContent = theme.label;
    document.getElementById('theme-description').textContent = theme.description;
    document.getElementById('dashboard-kicker').textContent = theme.kicker;
    const title = document.getElementById('dashboard-title');
    title.replaceChildren(document.createTextNode(theme.title));
    const dot = document.createElement('span');
    dot.textContent = name === 'terminal' ? '_' : '.';
    title.append(dot);
    document.getElementById('theme-footer').textContent = theme.footer;
    document.getElementById('notes-title').textContent = theme.notesTitle;
    document.getElementById('notes-copy').textContent = theme.notes;
    buttons.forEach(button => {
      const selected = button.dataset.theme === name;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    if (announce) document.getElementById('theme-announcement').textContent = `${theme.label.slice(5)} preview selected. Illustrative data only; the live dashboard theme is unchanged.`;
  }
  buttons.forEach((button, index) => {
    button.addEventListener('click', () => selectTheme(button.dataset.theme));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
      selectTheme(buttons[next].dataset.theme);
    });
  });
  selectTheme('hybrid', false);
})();
