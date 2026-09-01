/**
 * Development-only mock of the Calleegraph API (orchestrator prompt §5).
 *
 * This file is NOT part of the app: it lives outside `src/`, nothing in the
 * bundle imports it, and `.dockerignore` keeps it out of the image entirely.
 * It exists so the UI can be exercised — all four edge statuses, both density
 * bands, live status transitions — before the real backend is reachable.
 *
 *   npm run dev:mock                  # small graph (5 workflows → Detailed)
 *   MOCK_SIZE=large npm run dev:mock  # 50+ workflows  → Grouped
 *   BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev
 */
import { createServer } from 'node:http';

const PORT = Number(process.env.MOCK_PORT ?? 8001);
const SIZE = process.env.MOCK_SIZE === 'large' ? 'large' : 'small';

// --- state -----------------------------------------------------------------

let nextRepoId = 1;
const settings = {
  pat_set: false,
  github_actor_login: null,
  github_api_version: '2022-11-28',
  github_api_base: 'https://api.github.com',
};

const clients = new Set();

function broadcast(event, data) {
  const frame = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const client of clients) client.write(frame);
}

// --- fixtures --------------------------------------------------------------

function repo(fullName, status = 'done') {
  const [owner, name] = fullName.split('/');
  return {
    id: nextRepoId++,
    owner,
    name,
    full_name: fullName,
    default_branch: 'main',
    status,
    error: status === 'error' ? 'GitHub returned 404 for this repository.' : null,
    last_synced_commit_sha: status === 'done' ? 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678' : null,
    last_synced_at: status === 'done' ? new Date().toISOString() : null,
    created_at: new Date().toISOString(),
  };
}

function input(name, type, required, def = null) {
  return { name, type, required, default: def, description: null, options: null };
}

function workflow(repoFullName, path, name, kind, jobs, declaredInputs = []) {
  return {
    id: `${repoFullName}/${path}`,
    repository_full_name: repoFullName,
    path,
    name,
    kind,
    triggers: kind === 'reusable' ? ['workflow_call'] : ['push', 'pull_request'],
    jobs,
    declared_inputs: declaredInputs,
    declared_secrets: kind === 'reusable' ? ['GHCR_TOKEN'] : [],
    declared_outputs: [],
  };
}

function job(nodeId, key, { needs = [], condition = null, call = null, name = null } = {}) {
  return { id: `${nodeId}#${key}`, job_key: key, name, needs, condition, call };
}

function call(targetNodeId, targetRef, withMap, secretsMode = 'inherit') {
  return {
    target_node_id: targetNodeId,
    target_ref: targetRef,
    with: withMap,
    secrets_mode: secretsMode,
    secrets: secretsMode === 'explicit' ? ['GHCR_TOKEN'] : null,
  };
}

function edge(id, sourceNodeId, sourceJobId, targetNodeId, targetRef, status, issues, condition) {
  return {
    id,
    source_node_id: sourceNodeId,
    source_job_id: sourceJobId,
    target_node_id: targetNodeId,
    target_ref: targetRef,
    condition: condition ?? null,
    status,
    issues: issues ?? [],
  };
}

/** Five workflows and one of every edge status — the "Detailed" band. */
function smallGraph(repositories) {
  const app = 'acme/web-app';
  const ci = 'acme/platform-ci';

  const buildNode = workflow(
    ci,
    '.github/workflows/build-node.yml',
    'Build · Node',
    'reusable',
    [job(`${ci}/.github/workflows/build-node.yml`, 'build')],
    [input('node_version', 'string', true), input('cache', 'string', false, 'npm')],
  );
  const rollout = workflow(
    ci,
    '.github/workflows/k8s-rollout.yml',
    'Kubernetes rollout',
    'reusable',
    [job(`${ci}/.github/workflows/k8s-rollout.yml`, 'rollout')],
    [input('environment', 'string', true), input('image_tag', 'string', true)],
  );
  const notify = workflow(
    ci,
    '.github/workflows/notify-slack.yml',
    'Notify Slack',
    'reusable',
    [job(`${ci}/.github/workflows/notify-slack.yml`, 'notify')],
    [input('channel', 'string', true)],
  );

  const ciId = `${app}/.github/workflows/ci.yml`;
  const deployId = `${app}/.github/workflows/deploy-prod.yml`;

  const ciNode = workflow(app, '.github/workflows/ci.yml', 'Continuous integration', 'top_level', [
    job(ciId, 'lint'),
    job(ciId, 'build', {
      needs: ['lint'],
      call: call(buildNode.id, 'acme/platform-ci/.github/workflows/build-node.yml@v2', {
        node_version: "'20'",
        cache: "'npm'",
      }),
    }),
  ]);

  const deployNode = workflow(
    app,
    '.github/workflows/deploy-prod.yml',
    'Deploy · production',
    'top_level',
    [
      job(deployId, 'rollout', {
        call: call(rollout.id, 'acme/platform-ci/.github/workflows/k8s-rollout.yml@v3', {
          environment: "'production'",
          image_tag: '${{ github.sha }}',
          cluster_name: '${{ vars.PROD_CLUSTER }}',
        }),
      }),
      job(deployId, 'announce', {
        needs: ['rollout'],
        condition: 'always()',
        call: call(notify.id, 'acme/platform-ci/.github/workflows/notify-slack.yml@v2', {
          channel: "'#deploys'",
        }),
      }),
      job(deployId, 'audit', {
        condition: "steps.audit.outputs.ready == 'true'",
        call: call(
          null,
          'acme/compliance/.github/workflows/audit-log.yml@v1',
          { run_id: '${{ github.run_id }}' },
          'none',
        ),
      }),
    ],
  );

  const edges = [
    edge(
      'e-ok',
      ciNode.id,
      `${ciId}#build`,
      buildNode.id,
      'acme/platform-ci/.github/workflows/build-node.yml@v2',
      'ok',
      [],
      null,
    ),
    edge(
      'e-error',
      deployNode.id,
      `${deployId}#rollout`,
      rollout.id,
      'acme/platform-ci/.github/workflows/k8s-rollout.yml@v3',
      'error',
      [
        {
          severity: 'error',
          code: 'unknown_input',
          message:
            'deploy-prod.yml passes cluster_name to k8s-rollout.yml, which declares only environment and image_tag. GitHub Actions rejects the call at dispatch time.',
          suggestion:
            'Remove cluster_name from the caller, or declare it as an optional input on acme/platform-ci/.github/workflows/k8s-rollout.yml.',
          input_name: 'cluster_name',
        },
      ],
      null,
    ),
    edge(
      'e-warning',
      deployNode.id,
      `${deployId}#announce`,
      notify.id,
      'acme/platform-ci/.github/workflows/notify-slack.yml@v2',
      'warning',
      [
        {
          severity: 'warning',
          code: 'unresolvable_condition',
          message:
            'The condition always() on job announce cannot be evaluated statically, so this call may or may not run.',
          suggestion: null,
          input_name: null,
        },
      ],
      'always()',
    ),
    edge(
      'e-unresolved',
      deployNode.id,
      `${deployId}#audit`,
      null,
      'acme/compliance/.github/workflows/audit-log.yml@v1',
      'unresolved',
      [
        {
          severity: 'warning',
          code: 'unresolved_target',
          message:
            'acme/compliance is not tracked, so the inputs of audit-log.yml could not be checked.',
          suggestion: 'Add acme/compliance on the Repositories screen to resolve this call.',
          input_name: null,
        },
      ],
      "steps.audit.outputs.ready == 'true'",
    ),
  ];

  return {
    repositories,
    nodes: [ciNode, deployNode, buildNode, rollout, notify],
    edges,
    generated_at: new Date().toISOString(),
  };
}

/** 56 workflows across four repositories — the "Grouped" band. */
function largeGraph(repositories) {
  const nodes = [];
  const edges = [];
  const reusable = [];

  for (let i = 0; i < 16; i += 1) {
    const path = `.github/workflows/lib-${String(i).padStart(2, '0')}.yml`;
    const node = workflow(
      'acme/platform-ci',
      path,
      `Library job ${i}`,
      'reusable',
      [job(`acme/platform-ci/${path}`, 'run')],
      [input('ref', 'string', true), input('verbose', 'boolean', false, false)],
    );
    reusable.push(node);
    nodes.push(node);
  }

  const callers = ['acme/web-app', 'acme/api', 'acme/mobile'];
  callers.forEach((repoName, repoIndex) => {
    for (let i = 0; i < 14; i += 1) {
      const path = `.github/workflows/pipeline-${String(i).padStart(2, '0')}.yml`;
      const nodeId = `${repoName}/${path}`;
      const target = reusable[(repoIndex * 5 + i) % reusable.length];
      const broken = i % 7 === 3;
      const withMap = broken
        ? { ref: '${{ github.sha }}', not_declared: "'x'" }
        : { ref: '${{ github.sha }}' };
      const node = workflow(repoName, path, `Pipeline ${i}`, 'top_level', [
        job(nodeId, 'call', {
          call: call(target.id, `${target.id}@v1`, withMap),
          condition: i % 5 === 0 ? "github.ref == 'refs/heads/main'" : null,
        }),
      ]);
      nodes.push(node);
      edges.push(
        edge(
          `${nodeId}->${target.id}`,
          nodeId,
          `${nodeId}#call`,
          target.id,
          `${target.id}@v1`,
          broken ? 'error' : 'ok',
          broken
            ? [
                {
                  severity: 'error',
                  code: 'unknown_input',
                  message: `Pipeline ${i} passes not_declared, which ${target.path} does not declare.`,
                  suggestion: `Remove not_declared from ${repoName}/${path}.`,
                  input_name: 'not_declared',
                },
              ]
            : [],
          i % 5 === 0 ? "github.ref == 'refs/heads/main'" : null,
        ),
      );
    }
  });

  return { repositories, nodes, edges, generated_at: new Date().toISOString() };
}

const repositories =
  SIZE === 'large'
    ? [repo('acme/web-app'), repo('acme/api'), repo('acme/mobile'), repo('acme/platform-ci')]
    : [repo('acme/web-app'), repo('acme/platform-ci')];

let graph = SIZE === 'large' ? largeGraph(repositories) : smallGraph(repositories);

function rebuildGraph() {
  graph = { ...graph, repositories, generated_at: new Date().toISOString() };
  return graph;
}

// --- server ----------------------------------------------------------------

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(payload),
    'access-control-allow-origin': '*',
  });
  res.end(payload);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return {};
  }
}

/** Walks a freshly added repository through the real status sequence. */
function simulateSync(record) {
  const stages = ['fetching', 'parsing', 'done'];
  stages.forEach((status, position) => {
    setTimeout(
      () => {
        record.status = status;
        if (status === 'done') {
          record.last_synced_at = new Date().toISOString();
          record.last_synced_commit_sha = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef';
        }
        broadcast('repository_updated', record);
        if (status === 'done') broadcast('graph_updated', rebuildGraph());
      },
      1200 * (position + 1),
    );
  });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const path = url.pathname;

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'access-control-allow-headers': 'content-type',
    });
    res.end();
    return;
  }

  if (path === '/api/health')
    return json(res, 200, { status: 'ok', db: 'connected', cache: 'connected' });

  if (path === '/api/settings' && req.method === 'GET') return json(res, 200, settings);
  if (path === '/api/settings' && req.method === 'PUT') {
    const body = await readBody(req);
    if (body.github_pat) {
      settings.pat_set = true;
      settings.github_actor_login = 'mock-user';
    }
    if (body.github_api_version) settings.github_api_version = body.github_api_version;
    if (body.github_api_base) settings.github_api_base = body.github_api_base;
    return json(res, 200, settings);
  }

  if (path === '/api/repositories' && req.method === 'GET') return json(res, 200, repositories);
  if (path === '/api/repositories' && req.method === 'POST') {
    const body = await readBody(req);
    if (!body.full_name) return json(res, 422, { detail: 'full_name is required' });
    const record = repo(body.full_name, 'pending');
    repositories.push(record);
    broadcast('repository_updated', record);
    simulateSync(record);
    return json(res, 201, record);
  }

  const repoMatch = /^\/api\/repositories\/(\d+)(\/refresh)?$/.exec(path);
  if (repoMatch) {
    const id = Number(repoMatch[1]);
    const position = repositories.findIndex((item) => item.id === id);
    if (position === -1) return json(res, 404, { detail: 'Repository not found' });
    if (repoMatch[2] && req.method === 'POST') {
      const record = repositories[position];
      record.status = 'pending';
      broadcast('repository_updated', record);
      simulateSync(record);
      return json(res, 200, record);
    }
    if (req.method === 'DELETE') {
      const [removed] = repositories.splice(position, 1);
      graph.nodes = graph.nodes.filter((node) => node.repository_full_name !== removed.full_name);
      const alive = new Set(graph.nodes.map((node) => node.id));
      graph.edges = graph.edges
        .filter((item) => alive.has(item.source_node_id))
        .map((item) =>
          item.target_node_id && !alive.has(item.target_node_id)
            ? { ...item, target_node_id: null, status: 'unresolved' }
            : item,
        );
      broadcast('graph_updated', rebuildGraph());
      res.writeHead(204, { 'access-control-allow-origin': '*' });
      res.end();
      return;
    }
  }

  if (path === '/api/graph') return json(res, 200, rebuildGraph());

  if (path === '/api/events/stream') {
    res.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'access-control-allow-origin': '*',
      'x-accel-buffering': 'no',
    });
    res.write(': connected\n\n');
    clients.add(res);
    const keepAlive = setInterval(() => res.write(': keep-alive\n\n'), 15_000);
    req.on('close', () => {
      clearInterval(keepAlive);
      clients.delete(res);
    });
    return;
  }

  return json(res, 404, { detail: `No mock route for ${path}` });
});

server.listen(PORT, () => {
  process.stdout.write(
    `Calleegraph mock API on http://127.0.0.1:${PORT}/api (${SIZE} fixture, ${graph.nodes.length} workflows)\n` +
      `Run the app with: BACKEND_ORIGIN=http://127.0.0.1:${PORT} npm run dev\n`,
  );
});
