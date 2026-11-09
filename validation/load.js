import http from 'k6/http';
import { check } from 'k6';

// Login con bcrypt: carga CPU real de la aplicación, sin quemadores artificiales.
// Hasta 16 solicitudes/s, menos de cuatro minutos y un solo usuario sintético.
const base = __ENV.BASE_URL || 'http://backend.cloud-integrador.svc.cluster.local:8086';
export const options = {
  scenarios: {
    login: {
      executor: 'ramping-arrival-rate',
      startRate: 2, timeUnit: '1s', preAllocatedVUs: 20, maxVUs: 40,
      stages: [
        { duration: '20s', target: 2 },
        { duration: '60s', target: 8 },
        { duration: '60s', target: 16 },
        { duration: '20s', target: 2 },
        { duration: '20s', target: 0 },
      ],
      gracefulStop: '15s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<3000'],
    checks: ['rate>0.99'],
  },
};

export function setup() {
  const csrf = http.get(`${base}/api/users/csrf`);
  if (csrf.status !== 200) throw new Error(`CSRF setup HTTP ${csrf.status}`);
  const token = csrf.json('token');
  const username = `loadtest${Date.now()}`;
  const password = `Synthetic-${Date.now()}-LabOnly!`;
  const headers = { 'Content-Type': 'application/json', 'X-XSRF-TOKEN': token, Cookie: `XSRF-TOKEN=${token}` };
  const response = http.post(`${base}/api/users/register`, JSON.stringify({ username, email: `${username}@example.invalid`, password }), { headers });
  if (response.status !== 201) throw new Error(`Register setup HTTP ${response.status}`);
  return { username, password, token };
}

export default function (data) {
  const response = http.post(`${base}/api/users/login`, JSON.stringify({ username: data.username, password: data.password }), {
    headers: { 'Content-Type': 'application/json', 'X-XSRF-TOKEN': data.token, Cookie: `XSRF-TOKEN=${data.token}` },
    timeout: '10s', tags: { name: 'POST /api/users/login' },
  });
  check(response, { 'login HTTP 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  return { stdout: `\nK6_SUMMARY_BEGIN\n${JSON.stringify(data)}\nK6_SUMMARY_END\n` };
}
