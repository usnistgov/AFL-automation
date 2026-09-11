const form = document.getElementById('campaign-form');
const input = document.getElementById('campaign-id');
const loading = document.getElementById('loading');
const warnings = document.getElementById('warnings');
const dashboard = document.getElementById('dashboard');
const summary = document.getElementById('summary');

function compositionLabel(composition) {
  const entries = Object.entries(composition || {});
  return entries.length ? entries.map(([name, value]) => `${name.replace(/^stock_/, '')}=${Number(value).toPrecision(3)}`).join(', ') : 'Composition unavailable';
}

function showImage(container, record, fallback) {
  if (!record) {
    container.textContent = fallback;
    container.classList.add('empty');
    return;
  }
  const image = document.createElement('img');
  image.src = record.url;
  image.alt = 'Campaign image';
  image.loading = 'lazy';
  container.appendChild(image);
  if (record.composition && Object.keys(record.composition).length) {
    const caption = document.createElement('p');
    caption.className = 'image-caption';
    caption.textContent = compositionLabel(record.composition);
    container.appendChild(caption);
  }
  container.classList.remove('empty');
}

function renderWarnings(messages) {
  warnings.replaceChildren();
  if (!messages || !messages.length) { warnings.hidden = true; return; }
  const list = document.createElement('ul');
  messages.forEach(message => { const item = document.createElement('li'); item.textContent = message; list.appendChild(item); });
  warnings.appendChild(list);
  warnings.hidden = false;
}

function renderGallery(container, records) {
  (records || []).forEach(record => {
    const figure = document.createElement('figure');
    const image = document.createElement('img');
    image.src = record.url;
    image.alt = 'Campaign image';
    image.loading = 'lazy';
    const caption = document.createElement('figcaption');
    caption.textContent = compositionLabel(record.composition);
    figure.append(image, caption);
    container.appendChild(figure);
  });
}

function panelDataKey(panelSpec) {
  if (panelSpec.kind === 'spectrum') {
    return panelSpec.state === 'target' ? 'target_spectrum' : 'latest_spectrum';
  }
  if (panelSpec.kind === 'composition') {
    if (panelSpec.state === 'best') return 'best_composition';
    if (panelSpec.state === 'suggested') return 'suggested_composition';
    return 'latest_composition';
  }
  if (panelSpec.kind === 'progress') return 'objective';
  if (panelSpec.kind === 'design_space') return 'design_space';
  if (panelSpec.kind === 'spectra') return 'spectra';
  if (panelSpec.kind === 'image') {
    return panelSpec.state === 'target' ? 'target_image' : 'latest_image';
  }
  if (panelSpec.kind === 'gallery') return 'images';
  return null;
}

function renderDashboard(payload) {
  const plotKinds = new Set(['spectrum', 'spectra', 'composition', 'progress', 'design_space']);
  dashboard.replaceChildren();
  (payload.dashboard_layout || []).forEach(sectionSpec => {
    const section = document.createElement('section');
    section.className = 'dashboard-section';
    if (sectionSpec.title) {
      const heading = document.createElement('h2');
      heading.textContent = sectionSpec.title;
      section.appendChild(heading);
    }
    const grid = document.createElement('div');
    grid.className = 'panel-grid';
    grid.style.setProperty('--panel-columns', Math.max(1, Number(sectionSpec.columns) || 1));
    section.appendChild(grid);
    dashboard.appendChild(section);
    (sectionSpec.panels || []).forEach(panelSpec => {
      const dataKey = panelDataKey(panelSpec);
      const panel = document.createElement('article');
      panel.className = 'panel-card';
      if (panelSpec.title && !plotKinds.has(panelSpec.kind)) {
        const heading = document.createElement('h3');
        heading.textContent = panelSpec.title;
        panel.appendChild(heading);
      }
      const content = document.createElement('div');
      panel.appendChild(content);
      grid.appendChild(panel);
      if (plotKinds.has(panelSpec.kind)) {
        content.className = 'plot-slot';
        const figure = (payload.figures || {})[dataKey];
        if (figure) {
          const layout = {...(figure.layout || {}), autosize: true};
          if (panelSpec.title) layout.title = {text: panelSpec.title};
          Plotly.newPlot(content, figure.data || [], layout, {responsive: true, displaylogo: false})
            .then(() => requestAnimationFrame(() => Plotly.Plots.resize(content)));
        } else {
          content.classList.add('empty');
          content.textContent = 'No data available';
        }
      } else if (panelSpec.kind === 'image') {
        content.className = 'image-slot empty';
        showImage(content, (payload.current || {})[dataKey], 'No image available');
      } else if (panelSpec.kind === 'gallery') {
        panel.classList.add('gallery-panel');
        content.className = 'gallery';
        renderGallery(content, payload[dataKey] || []);
      }
    });
  });
}

async function refreshCampaign(event) {
  if (event) event.preventDefault();
  const campaignId = input.value.trim();
  loading.hidden = false;
  warnings.hidden = true;
  try {
    const query = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '';
    const response = await fetch(`/liveplot_data${query}`);
    const payload = await response.json();
    if (!response.ok || payload.status !== 'success') throw new Error(payload.message || `Request failed (${response.status})`);
    const counts = payload.counts || {};
    input.value = payload.campaign_id;
    summary.textContent = `${payload.campaign_id}: ${counts.compositions || 0} compositions, ${counts.images || 0} images, ${counts.spectra || 0} spectra`;
    renderWarnings(payload.warnings);
    renderDashboard(payload);
    if (campaignId) {
      const url = new URL(window.location.href); url.searchParams.set('campaign_id', campaignId); history.replaceState({}, '', url);
    }
  } catch (error) {
    renderWarnings([error.message]);
  } finally {
    loading.hidden = true;
  }
}

form.addEventListener('submit', refreshCampaign);
const requestedCampaign = new URLSearchParams(window.location.search).get('campaign_id');
if (requestedCampaign) input.value = requestedCampaign;
refreshCampaign();
