document.addEventListener('click', event => { const el=event.target.closest('[data-confirm]'); if (el && !window.confirm(el.dataset.confirm)) event.preventDefault(); });
