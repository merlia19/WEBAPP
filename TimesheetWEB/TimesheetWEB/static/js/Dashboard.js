/**
 * Danfoss Time Reporting — Dashboard JavaScript
 * Handles: monthly table generation, project autocomplete, submission to Flask API
 */

// ── State ─────────────────────────────────────────────────────────────────────
let monthDates     = [];   // [{date, day_name, day_num, is_weekend, is_today}, ...]
let projectNames   = [];   // ["Project A", "Project B", ...]
let selectedProject = -1;  // index in projectNames list

// ── On load ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadMonthDates();

  // Month/year selectors
  document.getElementById('month-sel').addEventListener('change', loadMonthDates);
  document.getElementById('year-sel').addEventListener('change',  loadMonthDates);

  // Autocomplete for project input
  const input = document.getElementById('project-input');
  input.addEventListener('input',   filterSuggestions);
  input.addEventListener('keydown', handleACKey);
  input.addEventListener('focus',   () => filterSuggestions());
  document.addEventListener('click', e => {
    if (!e.target.closest('.autocomplete-wrap')) hideDropdown();
  });

  // Auto-fill owner when project selected (from datalist)
  document.getElementById('project-input').addEventListener('change', autofillOwner);
});

// ── Month / dates ─────────────────────────────────────────────────────────────
async function loadMonthDates() {
  const month = document.getElementById('month-sel').value;
  const year  = document.getElementById('year-sel').value;

  const resp = await fetch(`/api/month-dates?month=${encodeURIComponent(month)}&year=${year}`);
  monthDates = await resp.json();

  const workingDays = monthDates.filter(d => !d.is_weekend).length;
  document.getElementById('month-subtitle').textContent =
    `📅  ${month} ${year}  —  ${monthDates.length} days  (${workingDays} working days)`;

  rebuildTable();
}

// ── Table ─────────────────────────────────────────────────────────────────────
function rebuildTable() {
  const container = document.getElementById('timesheet-table-container');

  if (projectNames.length === 0) {
    container.innerHTML = '<div class="empty-table-hint">No projects added. Click + ADD PROJECT to start.</div>';
    return;
  }

  let html = '<table id="timesheet-table"><thead><tr>';
  html += '<th class="th-project">Project</th>';

  monthDates.forEach(d => {
    let cls = d.is_weekend ? 'th-weekend' : (d.is_today ? 'th-today' : '');
    html += `<th class="${cls}">${d.day_name}<br>${d.day_num}</th>`;
  });
  html += '<th class="th-total">TOTAL</th></tr></thead><tbody>';

  projectNames.forEach((name, ri) => {
    const bg = ri % 2 === 0 ? '#fff' : '#f7f9fb';
    html += `<tr>`;
    html += `<td class="td-project" style="background:${bg}">${escHtml(name)}</td>`;

    monthDates.forEach((d, ci) => {
      const cls   = d.is_weekend ? 'td-weekend' : '';
      const extra = d.is_weekend ? 'disabled tabindex="-1" style="background:var(--weekend);color:var(--disabled-fg)"' : '';
      html += `<td class="${cls}" style="background:${d.is_weekend ? 'var(--weekend)' : bg}">
        <input class="hours-cell" type="number" min="0" max="24" step="0.5"
               data-row="${ri}" data-col="${ci}"
               oninput="updateRowTotal(${ri})"
               ${extra}/>
      </td>`;
    });

    html += `<td class="td-total" id="row-total-${ri}">0</td>`;
    html += `</tr>`;
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}

function updateRowTotal(rowIndex) {
  let total = 0;
  document.querySelectorAll(`input[data-row="${rowIndex}"]`).forEach(inp => {
    if (!inp.disabled) {
      const v = parseFloat(inp.value);
      if (!isNaN(v) && v >= 0) total += v;
    }
  });
  document.getElementById(`row-total-${rowIndex}`).textContent = total || 0;
  updateGrandTotal();
}

function updateGrandTotal() {
  let grand = 0;
  projectNames.forEach((_, ri) => {
    const el = document.getElementById(`row-total-${ri}`);
    if (el) grand += parseFloat(el.textContent) || 0;
  });
  document.getElementById('total-hours').value = grand || '';
}

// ── Projects ──────────────────────────────────────────────────────────────────
function addProject() {
  const input = document.getElementById('project-input');
  let name    = input.value.trim();

  if (!name) {
    let n = projectNames.length + 1;
    name  = `Project ${n}`;
    while (projectNames.includes(name)) name = `Project ${++n}`;
  }

  if (projectNames.includes(name)) {
    alert('This project is already in the list.');
    return;
  }

  autofillOwner();   // fill owner before clearing
  projectNames.push(name);
  input.value = '';
  hideDropdown();
  renderProjectList();
  rebuildTable();
}

function removeProject() {
  if (selectedProject < 0 || selectedProject >= projectNames.length) {
    alert('Please select a project to remove.');
    return;
  }
  projectNames.splice(selectedProject, 1);
  selectedProject = -1;
  renderProjectList();
  rebuildTable();
  updateGrandTotal();
}

function renderProjectList() {
  const ul = document.getElementById('project-list');
  ul.innerHTML = '';
  projectNames.forEach((name, i) => {
    const li = document.createElement('li');
    li.textContent = name;
    if (i === selectedProject) li.classList.add('selected');
    li.addEventListener('click', () => {
      selectedProject = i;
      renderProjectList();
    });
    ul.appendChild(li);
  });
}

// ── Autocomplete ──────────────────────────────────────────────────────────────
let acSelected = -1;

function filterSuggestions() {
  const typed = document.getElementById('project-input').value.trim().toLowerCase();
  const items = typed === ''
    ? PROJECT_SUGGESTIONS
    : PROJECT_SUGGESTIONS.filter(s => s.toLowerCase().includes(typed));

  renderDropdown(items, typed);
}

function renderDropdown(items, typed) {
  const dd = document.getElementById('ac-dropdown');
  if (items.length === 0) { dd.classList.add('hidden'); return; }

  dd.innerHTML = '';
  acSelected   = -1;

  items.forEach((item, i) => {
    const li   = document.createElement('li');
    // Highlight matching substring
    if (typed) {
      const idx = item.toLowerCase().indexOf(typed);
      li.innerHTML = escHtml(item.slice(0, idx))
        + '<mark>' + escHtml(item.slice(idx, idx + typed.length)) + '</mark>'
        + escHtml(item.slice(idx + typed.length));
    } else {
      li.textContent = item;
    }
    li.addEventListener('mousedown', e => {
      e.preventDefault();
      document.getElementById('project-input').value = item;
      hideDropdown();
      autofillOwner();
    });
    dd.appendChild(li);
  });

  dd.classList.remove('hidden');
}

function hideDropdown() {
  document.getElementById('ac-dropdown').classList.add('hidden');
  acSelected = -1;
}

function handleACKey(e) {
  const dd   = document.getElementById('ac-dropdown');
  const items = dd.querySelectorAll('li');

  if (e.key === 'Escape')  { hideDropdown(); return; }
  if (e.key === 'Enter')   {
    if (acSelected >= 0 && items[acSelected]) {
      document.getElementById('project-input').value = items[acSelected].textContent;
      hideDropdown();
      autofillOwner();
    } else {
      addProject();
    }
    e.preventDefault();
    return;
  }
  if (e.key === 'ArrowDown') {
    acSelected = Math.min(acSelected + 1, items.length - 1);
    highlightAC(items);
    e.preventDefault();
  }
  if (e.key === 'ArrowUp') {
    acSelected = Math.max(acSelected - 1, 0);
    highlightAC(items);
    e.preventDefault();
  }
}

function highlightAC(items) {
  items.forEach((li, i) => li.classList.toggle('selected', i === acSelected));
}

function autofillOwner() {
  const name  = document.getElementById('project-input').value.trim();
  const owner = CONSULTANT_OWNER_MAP[name] || '';
  if (owner) document.getElementById('owner').value = owner;
}

// ── Submit ────────────────────────────────────────────────────────────────────
async function submitReport() {
  const consultant = document.getElementById('consultant').value.trim();
  const type       = document.getElementById('proj-type').value;
  const month      = document.getElementById('month-sel').value;
  const year       = document.getElementById('year-sel').value;
  const owner      = document.getElementById('owner').value.trim();

  if (!consultant) { alert('Please enter Consultant Name.'); return; }
  if (!owner)      { alert('Please enter Project Owner.'); return; }
  if (!projectNames.length) { alert('Please add at least one project.'); return; }

  // Collect hours per project
  const projects = [];
  let grandTotal  = 0;

  for (let ri = 0; ri < projectNames.length; ri++) {
    const hours = {};
    let rowTotal = 0;

    document.querySelectorAll(`input[data-row="${ri}"]`).forEach((inp, ci) => {
      if (!inp.disabled && inp.value !== '') {
        const h = parseFloat(inp.value);
        if (!isNaN(h) && h >= 0) {
          hours[monthDates[ci].date] = h;
          rowTotal += h;
        }
      }
    });

    if (rowTotal < 0) { alert('Hours cannot be negative.'); return; }
    grandTotal += rowTotal;
    projects.push({ name: projectNames[ri], hours, total: rowTotal });
  }

  setStatus('⏳ Submitting to SharePoint…', 'var(--muted)');

  try {
    const resp = await fetch('/api/submit', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ consultant, type, month, year, owner, projects }),
    });
    const data = await resp.json();

    if (data.ok) {
      setStatus(`✅ Submitted ${projects.length} project(s) — ${data.grand_total} hrs  |  ${new Date().toLocaleTimeString()}`, '#166534');
      document.getElementById('status-msg').textContent = '✅ Submitted';
      alert(`✅ Timesheet submitted to SharePoint!\n\nConsultant: ${consultant}\nPeriod: ${month} ${year}\nProjects: ${projects.length}\nTotal Hours: ${data.grand_total}`);
    } else {
      setStatus('❌ Submission failed', 'var(--red)');
      alert(`SharePoint Submission Failed:\n\n${data.error}\n\nCheck:\n• CLIENT_SECRET is correct\n• App has Sites.Selected permission\n• SharePoint list column names match`);
    }
  } catch (err) {
    setStatus('❌ Network error', 'var(--red)');
    alert(`Network error: ${err.message}`);
  }
}

// ── Clear ─────────────────────────────────────────────────────────────────────
function clearForm() {
  document.getElementById('consultant').value = SSO_SIGNED_IN ? document.getElementById('consultant').value : '';
  document.getElementById('owner').value      = '';
  document.getElementById('total-hours').value = '';
  document.querySelectorAll('.hours-cell').forEach(inp => { if (!inp.disabled) inp.value = ''; });
  document.querySelectorAll('[id^="row-total-"]').forEach(el => el.textContent = '0');
  setStatus('', 'var(--muted)');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(msg, color) {
  const el = document.getElementById('submit-status');
  el.textContent = msg;
  el.style.color = color;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}