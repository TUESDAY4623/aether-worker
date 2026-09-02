const API = '/api/v1';
const REFRESH_MS = 5000;
let refreshTimer = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Page registry ──
const PAGES = {
  overview: 'Overview',
  workers: 'Workers',
  telemetry: 'Telemetry',
  thermal: 'Thermal Management',
  models: 'Model Capabilities',
  accelerators: 'Accelerators',
  resources: 'Resource Pool',
  partitioning: 'Partitioning',
  pipeline: 'Pipeline Schedule',
  topology: 'Topology Optimization',
  simulation: 'Simulation',
  'kv-cache': 'KV Cache',
  healing: 'Self-Healing',
  hierarchy: 'Hierarchy',
  planner: 'Planner',
};

function showPage(name) {
  document.querySelectorAll('.nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === name)
  );
  document.getElementById('page-title').textContent = PAGES[name] || name;
  const c = document.getElementById('page-content');
  c.innerHTML = '<div class="loading">Loading…</div>';
  renderPage(name).catch(err => {
    c.innerHTML = `<div class="error">Failed: ${err.message}</div>`;
  });
}

function badge(s) {
  const m = { healthy: 'green', ready: 'green', active: 'green', paired: 'green',
    warning: 'amber', throttling: 'amber', degraded: 'amber', stale: 'amber',
    critical: 'red', offline: 'red', failed: 'red', error: 'red' };
  return `<span class="badge badge-${m[(s||'').toLowerCase()]||'purple'}">${s||'unknown'}</span>`;
}

function bytes(n) {
  if (n === undefined || n === null) return '—';
  const u = ['B','KB','MB','GB','TB']; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + u[i];
}

function num(n) { return n === undefined || n === null ? '—' : n.toLocaleString(); }

function pct(n) { return n === undefined || n === null ? '—' : n.toFixed(1) + '%'; }

function table(headers, rows) {
  return `<div class="card mt-4"><table>
    <thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('')}</tbody>
  </table></div>`;
}

function kpis(items) {
  return `<div class="grid grid-4">${items.map(i =>
    `<div class="card"><div class="card-title">${i.title}</div><div class="card-value ${i.color||''}">${i.value}</div>${i.sub?`<div class="text-muted mt-2">${i.sub}</div>`:''}</div>`
  ).join('')}</div>`;
}

async function renderPage(name) {
  switch (name) {
    case 'overview':    return renderOverview();
    case 'workers':     return renderWorkers();
    case 'telemetry':   return renderTelemetry();
    case 'thermal':     return renderThermal();
    case 'models':      return renderModels();
    case 'accelerators':return renderAccelerators();
    case 'resources':   return renderResources();
    case 'partitioning':return renderPartitioning();
    case 'pipeline':    return renderPipeline();
    case 'topology':    return renderTopology();
    case 'simulation':  return renderSimulation();
    case 'kv-cache':    return renderKVCache();
    case 'healing':     return renderHealing();
    case 'hierarchy':   return renderHierarchy();
    case 'planner':     return renderPlanner();
  }
}

// ── Renderers ──
async function renderOverview() {
  const [health, workers, telemetry, thermal] = await Promise.all([
    api('/health').catch(e => null),
    api(`${API}/workers`).catch(e => []),
    api(`${API}/telemetry`).catch(e => ({})),
    api(`${API}/thermal`).catch(e => ({})),
  ]);

  const workerList = Array.isArray(workers) ? workers : [];
  const paired = workerList.filter(w => w.paired).length;
  const thermalData = thermal.devices || {};
  const hotCount = Object.values(thermalData).filter(d => d.state === 'critical' || d.state === 'throttling').length;

  document.getElementById('page-content').innerHTML = `
    ${kpis([
      { title: 'Health', value: health?.status || 'unknown', color: health?.status === 'healthy' ? 'text-green' : 'text-amber' },
      { title: 'Workers', value: workerList.length, sub: `${paired} paired` },
      { title: 'Telemetry', value: Object.keys(telemetry.telemetry || {}).length, sub: 'devices reporting' },
      { title: 'Thermal Alerts', value: hotCount, color: hotCount > 0 ? 'text-amber' : 'text-green' },
    ])}
    ${workerList.length ? table(
      ['Device', 'Display Name', 'State', 'Paired', 'Last Seen', 'Thermal'],
      workerList.map(w => `<tr>
        <td>${w.device_id}</td><td>${w.display_name}</td>
        <td>${badge(w.state)}</td><td>${w.paired ? badge('paired') : '—'}</td>
        <td>${w.last_seen ? new Date(w.last_seen).toLocaleTimeString() : '—'}</td>
        <td>${w.thermal_state || '—'}</td>
      </tr>`)
    ) : '<div class="card mt-4 text-muted">No workers registered yet</div>'}
  `;
}

async function renderWorkers() {
  const list = await api(`${API}/workers`);
  document.getElementById('page-content').innerHTML = list.length ? table(
    ['Device ID', 'Display Name', 'State', 'Paired', 'Peer', 'Last Seen'],
    list.map(w => `<tr>
      <td>${w.device_id}</td><td>${w.display_name}</td>
      <td>${badge(w.state)}</td><td>${w.paired?'Yes':'No'}</td>
      <td>${w.peer_addr||'—'}</td>
      <td>${w.last_seen ? new Date(w.last_seen).toLocaleTimeString() : '—'}</td>
    </tr>`)
  ) : '<div class="loading">No workers</div>';
}

async function renderTelemetry() {
  const data = await api(`${API}/telemetry`);
  const t = data.telemetry || {};
  const rows = Object.entries(t).map(([id, m]) => `<tr>
    <td>${id}</td><td>${pct(m.cpu_util)}</td><td>${pct(m.memory_util)}</td>
    <td>${m.temperature_c ?? '—'}°C</td><td>${m.network_mbps ?? '—'} Mbps</td>
    <td>${num(m.active_inferences)}</td>
  </tr>`).join('');
  document.getElementById('page-content').innerHTML = rows ? table(
    ['Device', 'CPU', 'Memory', 'Temp', 'Network', 'Active Jobs'], rows
  ) : '<div class="loading">No telemetry reports yet — workers must be paired and reporting</div>';
}

async function renderThermal() {
  const data = await api(`${API}/thermal`);
  const devs = data.devices || {};
  const entries = Object.entries(devs);
  const counts = entries.reduce((a, [,d]) => {
    a[d.state] = (a[d.state]||0)+1; return a;
  }, {});
  document.getElementById('page-content').innerHTML = `
    ${kpis([
      { title: 'Healthy', value: counts.healthy||0, color: 'text-green' },
      { title: 'Warning', value: counts.warning||0, color: counts.warning ? 'text-amber' : '' },
      { title: 'Throttling', value: counts.throttling||0, color: counts.throttling ? 'text-amber' : '' },
      { title: 'Critical', value: counts.critical||0, color: counts.critical ? 'text-red' : '' },
    ])}
    ${entries.length ? table(
      ['Device', 'Temp °C', 'State', 'Power Mode'],
      entries.map(([id, d]) => `<tr>
        <td>${id}</td><td>${d.temperature_c?.toFixed(1) ?? '—'}</td>
        <td>${badge(d.state)}</td><td>${d.power_mode || '—'}</td>
      </tr>`)
    ) : '<div class="card mt-4 text-muted">No thermal data — connect workers</div>'}
  `;
}

// Phase 7/8 components are wired into the separate api/server.py module.
// These pages surface that data when the controller is running that server too.

async function renderModels() {
  const data = await api(`${API}/models`);
  const models = data.models || [];
  document.getElementById('page-content').innerHTML = models.length ? `
    ${kpis([
      { title: 'Models', value: data.count, sub: 'registered profiles' },
      { title: 'Distributed', value: (await api(`${API}/models/distributed-compatible`)).count, sub: 'support distributed' },
    ])}
    ${table(
      ['ID', 'Name', 'Architecture', 'Runtimes', 'Quant', 'Operators'],
      models.map(m => `<tr>
        <td><code>${m.model_id}</code></td><td>${m.model_name}</td>
        <td>${m.architecture_family || '—'}</td>
        <td>${(m.supported_runtimes||[]).slice(0,3).join(', ')}${(m.supported_runtimes||[]).length > 3 ? '…' : ''}</td>
        <td>${(m.quantization_formats||[]).join(', ')}</td>
        <td>${(m.required_operators||[]).length}</td>
      </tr>`)
    )
  } : '<div class="loading">No models registered</div>';
}

async function renderAccelerators() {
  const data = await api(`${API}/accelerators`);
  const accs = data.accelerators || [];
  const available = accs.filter(a => a.available).length;
  document.getElementById('page-content').innerHTML = accs.length ? `
    ${kpis([
      { title: 'Accelerators', value: data.count, sub: 'total devices' },
      { title: 'Available', value: available, color: available ? 'text-green' : '' },
    ])}
    ${table(
      ['Type', 'Device ID', 'Model', 'TOPS', 'Memory', 'Temp °C', 'State'],
      accs.map(a => `<tr>
        <td>${badge(a.accelerator_type)}</td><td><code>${a.device_id}</code></td>
        <td>${a.model_name || '—'}</td><td>${a.peak_tops ?? '—'}</td>
        <td>${a.memory_mb ? num(a.memory_mb) + ' MB' : '—'}</td>
        <td>${a.temperature_c?.toFixed(1) ?? '—'}</td>
        <td>${badge(a.state)}</td>
      </tr>`)
    )
  } : '<div class="loading">No accelerators detected — connect a worker to see NPU/GPU</div>';
}

async function renderResources() {
  const data = await api(`${API}/resources`);
  const devices = data.devices || {};
  const entries = Object.values(devices);
  const totalCpu = entries.reduce((s, d) => s + (d.cpu_cores || 0), 0);
  document.getElementById('page-content').innerHTML = entries.length ? `
    ${kpis([
      { title: 'Devices', value: entries.length, sub: `${totalCpu} CPU cores` },
      { title: 'Reservations', value: data.reservation_count, sub: 'active' },
    ])}
    ${table(
      ['Device', 'CPU Cores', 'CPU Util', 'Memory', 'Avail Mem', 'BW', 'NPU', 'GPU', 'Thermal'],
      entries.map(d => `<tr>
        <td><code>${d.device_id}</code></td>
        <td>${d.cpu_cores}</td><td>${pct(d.cpu_utilization_pct)}</td>
        <td>${d.memory_total_mb ? num(d.memory_total_mb) + ' MB' : '—'}</td>
        <td>${d.memory_available_mb ? num(d.memory_available_mb) + ' MB' : '—'}</td>
        <td>${d.bandwidth_mbps ? num(d.bandwidth_mbps) + ' Mbps' : '—'}</td>
        <td>${d.npu_available ? badge('ready') : '—'}</td>
        <td>${d.gpu_available ? badge('ready') : '—'}</td>
        <td>${badge(d.thermal_state)}</td>
      </tr>`)
    )
  } : '<div class="loading">Resource pool is empty — register a device via <code>aether.resource_pool</code></div>';
}

async function renderPartitioning() {
  const data = await api(`${API}/resources`).catch(() => ({ devices: {} }));
  const devs = Object.keys(data.devices || {});
  document.getElementById('page-content').innerHTML = `
    <div class="card">
      <div class="card-title">Model Partitioner</div>
      <p class="text-muted mb-4">Layer-to-device graph mapping with latency-balanced strategies.</p>
      ${devs.length ? `
        <label class="toggle mb-4">
          <select id="partition-model" class="select">
            <option value="">Select model…</option>
          </select>
        </label>
        <button class="btn" id="btn-partition">Run Partition</button>
        <div id="partition-result" class="mt-4"></div>
      ` : '<div class="text-muted">No devices available — connect workers first</div>'}
    </div>
  `;
  if (devs.length) {
    const models = await api(`${API}/models`).catch(() => ({ models: [] }));
    const sel = document.getElementById('partition-model');
    (models.models || []).forEach(m => {
      const o = document.createElement('option');
      o.value = m.model_id; o.textContent = `${m.model_name} (${m.model_id})`;
      sel.appendChild(o);
    });
    const btn = document.getElementById('btn-partition');
    btn.onclick = async () => {
      const modelId = sel.value;
      if (!modelId) return;
      btn.disabled = true;
      btn.textContent = 'Partitioning…';
      try {
        const plan = await api(`${API}/plans`, {
          method: 'POST',
          body: JSON.stringify({ model_id: modelId, model_layers: 32, strategy: 'automatic' }),
        });
        document.getElementById('partition-result').innerHTML = `
          <div class="card mt-4">
            <div class="card-title">Plan: ${plan.plan_id}</div>
            <p>Confidence: ${(plan.confidence * 100).toFixed(1)}%</p>
            <p>Est. latency: ${plan.estimated_latency_ms?.toFixed(0) ?? '—'} ms</p>
            <p>Est. energy: ${plan.estimated_energy_j?.toFixed(1) ?? '—'} J</p>
            <p>Max temp: ${plan.max_temperature_c?.toFixed(1) ?? '—'}°C</p>
            <pre>${JSON.stringify(plan.device_assignments, null, 2)}</pre>
          </div>
        `;
      } catch (e) {
        document.getElementById('partition-result').innerHTML = `<div class="error mt-4">Failed: ${e.message}</div>`;
      } finally {
        btn.disabled = false;
        btn.textContent = 'Run Partition';
      }
    };
  }
}

async function renderPipeline() {
  const data = await api(`${API}/plans`).catch(() => ({ plans: [] }));
  document.getElementById('page-content').innerHTML = data.plans.length ? `
    <div class="card"><div class="card-title">Pipeline Schedule</div>
      <p class="text-muted mb-4">Execution plans as pipeline stages.</p>
      ${table(
        ['Plan ID', 'Model', 'Strategy', 'Latency (ms)', 'Energy (J)', 'Confidence', 'Fallback'],
        data.plans.map(p => `<tr>
          <td><code>${p.plan_id}</code></td><td>${p.model_id}</td>
          <td>${p.strategy}</td><td>${p.estimated_latency_ms?.toFixed(0) ?? '—'}</td>
          <td>${p.estimated_energy_j?.toFixed(1) ?? '—'}</td>
          <td>${p.confidence !== undefined ? (p.confidence * 100).toFixed(0) + '%' : '—'}</td>
          <td>${p.fallback_plan ? '<code>' + p.fallback_plan + '</code>' : '—'}</td>
        </tr>`)
      )
    }
    </div>
  ` : '<div class="loading">No execution plans yet — create one from the Planner page</div>';
}

async function renderTopology() {
  const hierarchy = await api(`${API}/hierarchy`).catch(() => ({ nodes: {} }));
  const nodes = hierarchy.nodes || {};
  const entries = Object.values(nodes);
  document.getElementById('page-content').innerHTML = entries.length ? `
    <div class="card"><div class="card-title">Network Topology</div>
      <p class="text-muted mb-4">Hierarchy nodes as topology graph.</p>
      ${table(
        ['Node ID', 'Role', 'Parent', 'Children', 'Max Children'],
        entries.map(n => `<tr>
          <td><code>${n.node_id}</code></td><td>${badge(n.role)}</td>
          <td>${n.parent_id || '—'}</td><td>${(n.children || []).join(', ') || '—'}</td>
          <td>${n.max_children}</td>
        </tr>`)
      )
    }
    </div>
  ` : '<div class="loading">No topology — register nodes from the Hierarchy page</div>';
}

async function renderSimulation() {
  const list = await api(`${API}/simulation`).catch(() => ({ simulations: [] }));
  const sims = list.simulations || [];
  document.getElementById('page-content').innerHTML = sims.length ? `
    <div class="card"><div class="card-title">Simulation Results</div>
      <p class="text-muted mb-4">Past simulation runs.</p>
      ${table(
        ['ID', 'Latency (ms)', 'Max Temp', 'Thermal OK', 'Warnings', 'Score'],
        sims.map(s => `<tr>
          <td><code>${s.simulation_id}</code></td>
          <td>${s.total_latency_ms?.toFixed(0) ?? '—'}</td>
          <td>${s.max_temperature_c?.toFixed(1) ?? '—'}°C</td>
          <td>${s.any_thermal_violation ? badge('critical') : badge('healthy')}</td>
          <td>${(s.warnings || []).join(', ') || '—'}</td>
          <td>${s.score?.toFixed(1) ?? '—'}</td>
        </tr>`)
      )
    }
    </div>
  ` : '<div class="loading">No simulations yet — run one via <code>aether.execution.simulation</code></div>';
}

async function renderKVCache() {
  document.getElementById('page-content').innerHTML = placeholder('KV Cache Fabric', 'Distributed KV Cache', [
    'Tiered cache across local + remote devices',
    'Eviction policies (LRU, recency, weight)',
    'Block-level prefetch & pin',
    'Fragmentation reports & compaction',
  ]);
}

async function renderHealing() {
  const data = await api(`${API}/healing`);
  const health = data.health || {};
  const degraded = data.degraded_devices || [];
  const history = data.failover_history || [];
  const entries = Object.values(health);
  document.getElementById('page-content').innerHTML = `
    ${kpis([
      { title: 'Monitored', value: entries.length, sub: 'devices' },
      { title: 'Degraded', value: degraded.length, color: degraded.length ? 'text-amber' : '' },
      { title: 'Failover Events', value: history.length, sub: 'recovery actions' },
    ])}
    ${entries.length ? table(
      ['Device', 'Status', 'Last Check', 'Failures', 'Recovery Attempts', 'Degraded Caps'],
      entries.map(h => `<tr>
        <td><code>${h.device_id}</code></td><td>${badge(h.status)}</td>
        <td>${h.last_check ? new Date(h.last_check).toLocaleTimeString() : '—'}</td>
        <td>${h.failure_count}</td><td>${h.recovery_attempts}</td>
        <td>${(h.degraded_capabilities || []).join(', ') || '—'}</td>
      </tr>`)
    ) : '<div class="card mt-4 text-muted">No devices monitored yet — run workers to register</div>'}
    ${history.length ? `
      <div class="card mt-4"><div class="card-title">Failover History</div>
        ${table(
          ['Action ID', 'Failed Device', 'Action', 'Target', 'Layers Migrated', 'Recovery (ms)', 'Success'],
          history.map(a => `<tr>
            <td><code>${a.action_id}</code></td><td><code>${a.failed_device_id}</code></td>
            <td>${a.action_type}</td><td><code>${a.target_device_id || '—'}</code></td>
            <td>${(a.migrated_layers || []).join(', ') || '—'}</td>
            <td>${a.estimated_recovery_ms ?? '—'}</td>
            <td>${a.success ? badge('ready') : badge('failed')}</td>
          </tr>`)
        )
      }
      </div>
    ` : ''}
  `;
}

async function renderHierarchy() {
  const data = await api(`${API}/hierarchy`);
  const nodes = data.nodes || {};
  const summary = data.role_summary || {};
  const events = data.events || [];
  const entries = Object.values(nodes);
  document.getElementById('page-content').innerHTML = `
    ${kpis([
      { title: 'Nodes', value: entries.length, sub: 'in hierarchy' },
      { title: 'Roles', value: Object.keys(summary).length, sub: 'distinct' },
      { title: 'Events', value: events.length, sub: 'recent' },
    ])}
    <div class="card mt-4"><div class="card-title">Role Summary</div>
      <div class="grid grid-4 mt-2">
        ${Object.entries(summary).map(([role, count]) =>
          `<div class="card"><div class="card-value">${count}</div><div class="text-muted">${role}</div></div>`
        ).join('') || '<div class="text-muted">No roles assigned</div>'}
      </div>
    </div>
    ${entries.length ? table(
      ['Node ID', 'Role', 'Parent', 'Children', 'Max Children'],
      entries.map(n => `<tr>
        <td><code>${n.node_id}</code></td><td>${badge(n.role)}</td>
        <td>${n.parent_id || '—'}</td>
        <td>${(n.children || []).join(', ') || '—'}</td><td>${n.max_children}</td>
      </tr>`)
    ) : '<div class="card mt-4 text-muted">No nodes — use "Register Node" below</div>'}
    <div class="card mt-4">
      <div class="card-title">Register Node</div>
      <div class="flex gap-2 mt-2">
        <input id="h-node-id" class="input" placeholder="Node ID" />
        <select id="h-node-role" class="select">
          <option value="super">Super</option>
          <option value="primary">Primary</option>
          <option value="secondary">Secondary</option>
          <option value="worker" selected>Worker</option>
          <option value="standby">Standby</option>
        </select>
        <input id="h-node-parent" class="input" placeholder="Parent ID (optional)" />
        <button class="btn" id="btn-register-node">Register</button>
      </div>
      <div id="h-node-result" class="mt-2"></div>
    </div>
    ${events.length ? `
      <div class="card mt-4"><div class="card-title">Recent Events</div>
        ${table(
          ['Event ID', 'Type', 'Node', 'Old Role', 'New Role', 'Time'],
          events.map(e => `<tr>
            <td><code>${e.event_id}</code></td><td>${e.event_type}</td>
            <td><code>${e.node_id}</code></td>
            <td>${badge(e.old_role)}</td><td>${badge(e.new_role)}</td>
            <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
          </tr>`)
        )
      }
      </div>
    ` : ''}
  `;
  // Wire up register button
  setTimeout(() => {
    const btn = document.getElementById('btn-register-node');
    if (!btn) return;
    btn.onclick = async () => {
      const nodeId = document.getElementById('h-node-id').value.trim();
      const role = document.getElementById('h-node-role').value;
      const parent = document.getElementById('h-node-parent').value.trim();
      if (!nodeId) return;
      btn.disabled = true;
      try {
        const result = await api(`${API}/hierarchy/nodes`, {
          method: 'POST',
          body: JSON.stringify({ node_id: nodeId, role, parent_id: parent }),
        });
        document.getElementById('h-node-result').innerHTML = `<span class="text-green">Registered: ${result.node_id} as ${result.role}</span>`;
        showPage('hierarchy');
      } catch (e) {
        document.getElementById('h-node-result').innerHTML = `<span class="text-red">Failed: ${e.message}</span>`;
      } finally {
        btn.disabled = false;
      }
    };
  }, 0);
}

async function renderPlanner() {
  const list = await api(`${API}/plans`).catch(() => ({ plans: [] }));
  const plans = list.plans || [];
  document.getElementById('page-content').innerHTML = `
    <div class="card"><div class="card-title">Autonomous Planner</div>
      <p class="text-muted mb-4">LLM-driven execution plan generation.</p>
      <div class="flex gap-2 mb-4">
        <select id="plan-model" class="select">
          <option value="">Select model…</option>
        </select>
        <select id="plan-strategy" class="select">
          <option value="automatic">Automatic</option>
          <option value="low_latency">Low Latency</option>
          <option value="throughput">Throughput</option>
          <option value="energy_efficient">Energy Efficient</option>
          <option value="thermal_safe">Thermal Safe</option>
        </select>
        <button class="btn" id="btn-create-plan">Create Plan</button>
      </div>
      <div id="plan-result" class="mt-2"></div>
      ${plans.length ? table(
        ['Plan ID', 'Model', 'Strategy', 'Latency (ms)', 'Energy (J)', 'Max Temp', 'Confidence', 'Fallback'],
        plans.map(p => `<tr>
          <td><code>${p.plan_id}</code></td><td>${p.model_id}</td>
          <td>${p.strategy}</td><td>${p.estimated_latency_ms?.toFixed(0) ?? '—'}</td>
          <td>${p.estimated_energy_j?.toFixed(1) ?? '—'}</td>
          <td>${p.max_temperature_c?.toFixed(1) ?? '—'}°C</td>
          <td>${p.confidence !== undefined ? (p.confidence * 100).toFixed(0) + '%' : '—'}</td>
          <td>${p.fallback_plan ? '<code>' + p.fallback_plan + '</code>' : '—'}</td>
        </tr>`)
      ) : '<div class="text-muted mt-4">No plans yet</div>'}
    </div>
  `;
  // Populate model dropdown
  try {
    const models = await api(`${API}/models`).catch(() => ({ models: [] }));
    const sel = document.getElementById('plan-model');
    if (sel) {
      (models.models || []).forEach(m => {
        const o = document.createElement('option');
        o.value = m.model_id; o.textContent = `${m.model_name} (${m.model_id})`;
        sel.appendChild(o);
      });
    }
  } catch {}
  // Wire up create button
  setTimeout(() => {
    const btn = document.getElementById('btn-create-plan');
    if (!btn) return;
    btn.onclick = async () => {
      const modelId = document.getElementById('plan-model').value;
      const strategy = document.getElementById('plan-strategy').value;
      if (!modelId) return;
      btn.disabled = true;
      try {
        const plan = await api(`${API}/plans`, {
          method: 'POST',
          body: JSON.stringify({ model_id: modelId, model_layers: 32, strategy }),
        });
        document.getElementById('plan-result').innerHTML = `
          <div class="card mt-2 text-green">
            Plan created: <code>${plan.plan_id}</code> — confidence ${(plan.confidence * 100).toFixed(1)}%,
            latency ${plan.estimated_latency_ms?.toFixed(0)}ms
          </div>
        `;
        showPage('planner');
      } catch (e) {
        document.getElementById('plan-result').innerHTML = `<div class="error mt-2">Failed: ${e.message}</div>`;
      } finally {
        btn.disabled = false;
      }
    };
  }, 0);
}

function placeholder(title, subtitle, bullets, action = '') {
  return `
    <div class="card">
      <div class="card-title">${subtitle}</div>
      <h3 class="mt-2 mb-4">${title}</h3>
      <p class="text-muted mb-4">This subsystem is implemented in <code>aether/intelligence/</code> and <code>aether/execution/</code>. It is exercised by the controller via the <code>aether/api/server.py</code> FastAPI app — not the lightweight controller API.</p>
      <ul style="line-height:1.8;padding-left:20px">
        ${bullets.map(b => `<li>${b}</li>`).join('')}
      </ul>
      ${action ? `<div class="mt-4">${action}</div>` : ''}
    </div>
  `;
}

// ── Wire up ──
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', e => {
      e.preventDefault();
      if (el.dataset.page) showPage(el.dataset.page);
    });
  });
  document.getElementById('btn-refresh').addEventListener('click', () => {
    const a = document.querySelector('.nav-item.active');
    if (a) showPage(a.dataset.page);
  });
  const auto = document.getElementById('auto-refresh');
  const tick = () => {
    if (!auto.checked) return;
    const a = document.querySelector('.nav-item.active');
    if (a) showPage(a.dataset.page);
  };
  auto.addEventListener('change', () => {
    clearInterval(refreshTimer);
    if (auto.checked) refreshTimer = setInterval(tick, REFRESH_MS);
  });
  refreshTimer = setInterval(tick, REFRESH_MS);
  showPage('overview');
});
