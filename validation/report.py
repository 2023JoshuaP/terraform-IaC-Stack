#!/usr/bin/env python3
"""Genera un informe legible a partir de evidencias reales, sin inventar capturas."""
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from common import directory, redact

destination = directory()


def read_json(name):
    path = destination / name
    return json.loads(path.read_text()) if path.exists() else None


def esc(value):
    return html.escape(str(value))


def chart(rows, key, title, color, maximum=None):
    points = [(row["elapsed_seconds"], row[key]) for row in rows if row.get(key) is not None]
    if not points:
        return ""
    width, height = 900, 240
    x_max = max(x for x, _ in points) or 1
    y_max = maximum or max(y for _, y in points) * 1.15 or 1
    coordinates = " ".join(f"{55 + x / x_max * 820:.2f},{200 - y / y_max * 165:.2f}" for x, y in points)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<rect width="900" height="240" fill="#fff"/><text x="55" y="20" font-size="16">{esc(title)}</text>
<path d="M55 35V200H875" stroke="#94a3b8" fill="none"/>
<text x="5" y="45" font-size="13">{y_max:.1f}</text><text x="25" y="200" font-size="13">0</text>
<text x="55" y="225" font-size="13">0 s</text><text x="800" y="225" font-size="13">{x_max:.0f} s</text>
<polyline points="{coordinates}" stroke="{color}" stroke-width="3" fill="none"/>
</svg>'''
    filename = f"chart-{key}.svg"
    (destination / filename).write_text(svg)
    return f'<figure><img src="{filename}" alt="{esc(title)}"><figcaption>Muestras reales, no simuladas. Eje X: segundos desde el lanzamiento del Job.</figcaption></figure>'


parts = ["""<!doctype html><html lang="es"><meta charset="utf-8"><title>Evidencias Cloud Integrador</title>
<style>body{font:16px system-ui;margin:36px auto;max-width:1100px;padding:0 24px;background:#f4f7fb;color:#172033}
section,header{background:white;padding:24px;margin:20px 0;border-radius:12px;border:1px solid #dce3ef}
h1,h2{margin-top:0}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce3ef;padding:10px;text-align:left}
pre{background:#0f172a;color:#e2e8f0;padding:16px;overflow:auto;white-space:pre-wrap;font-size:12px}
img{width:100%}figure{margin:20px 0}figcaption,.note{font-size:13px;color:#475569}a{color:#174db0}
@media print{body{margin:0;background:white}section{break-inside:avoid}details{display:block}}</style>
<header><h1>Cloud Integrador · Evidencias de ejecución</h1>""",
         f"<p>Generado UTC: {datetime.now(timezone.utc).isoformat()}</p>",
         "<p>Reporte generado a partir de comandos y pruebas reales. No es una captura de la consola AWS.</p>",
         "<p><b>CI/CD pospuesto por decisión del equipo.</b> La eliminación completa del entorno tampoco se ejecuta mientras se preparan las capturas.</p></header>"]

parts.append("<section><h2>1. Aplicación, Kubernetes y operación</h2><p>Frontend y backend en EKS; PostgreSQL privado en RDS; entrada ALB. Los logs y comandos completos están enlazados al final.</p>")
for name in ("baseline-workloads.txt", "baseline-cpu-memory.txt", "baseline-functional.txt"):
    if (destination / name).exists():
        parts.append(f"<h3>{esc(name)}</h3><pre>{esc(redact((destination / name).read_text()))}</pre>")
parts.append("</section><section><h2>2. Pruebas de aplicación</h2><table><tr><th>Componente</th><th>Tests</th><th>Fallos</th><th>Errores</th><th>Omitidos</th><th>Reportes</th></tr>")
for component in ("backend", "frontend"):
    data = read_json(f"tests-{component}/summary.json")
    if data:
        parts.append(f'<tr><td>{component}</td><td>{data["tests"]}</td><td>{data["failures"]}</td><td>{data["errors"]}</td><td>{data["skipped"]}</td><td><a href="{esc(data["report_directory"])}/summary.json">JSON</a></td></tr>')
        if data.get("coverage", {}).get("LINE"):
            counter = data["coverage"]["LINE"]
            total = counter["covered"] + counter["missed"]
            parts.append(f'<tr><td colspan="6">Cobertura de líneas backend (JaCoCo): {100 * counter["covered"] / total:.1f}% ({counter["covered"]}/{total}).</td></tr>')
    else:
        parts.append(f"<tr><td>{component}</td><td colspan=5>Pendiente de reporte satisfactorio</td></tr>")
parts.append("</table><p class=note>Los informes corresponden al commit desplegado. Las pruebas de repositorio no sustituyen la integración externa con RDS, registrada en la comprobación funcional.</p></section>")

recovery = read_json("recovery-result.json")
parts.append("<section><h2>3. Recuperación ante eliminación de pod</h2>")
if recovery:
    parts.append(f'<p>Pod eliminado: <b>{esc(recovery["old_pod"])}</b><br>Reemplazo automático: <b>{esc(recovery["new_pod"])}</b><br>Tiempo observado hasta Ready: <b>{recovery["observed_seconds"]} s</b>.</p>')
    parts.append("<p class=note>Se prueba recuperación automática, no alta disponibilidad: con una réplica puede existir interrupción breve.</p>")
else:
    parts.append("<p>Pendiente.</p>")
parts.append("</section><section><h2>4. Carga, HPA y métricas</h2>")
load = read_json("load-result.json")
rows = read_json("load-timeseries.json") or []
if load:
    parts.append(f'<p>k6 satisfactorio: <b>{esc(load["k6_succeeded"])}</b> · Máximo de réplicas observado: <b>{load["max_replicas"]}</b> · Retorno automático a una réplica: <b>{esc(load["scaled_back_to_one"])}</b>.</p>')
summary = read_json("load-k6-summary.json")
if summary:
    metrics = summary["metrics"]
    count = metrics.get("http_reqs", {}).get("values", {}).get("count", "N/D")
    rate = metrics.get("http_req_failed", {}).get("values", {}).get("rate")
    p95 = metrics.get("http_req_duration", {}).get("values", {}).get("p(95)")
    rate_label = f'{rate * 100:.2f}%' if rate is not None else 'N/D'
    latency_label = f'{p95:.1f} ms' if p95 is not None else 'N/D'
    parts.append(f'<p>Solicitudes: <b>{esc(count)}</b> · Error HTTP: <b>{rate_label}</b> · Latencia p95: <b>{latency_label}</b>.</p>')
    parts.append('<p>Umbrales: errores HTTP &lt; 1%, checks &gt; 99%, latencia p95 &lt; 3000 ms.</p>')
for key, title, color, maximum in (
    ("backend_current", "Réplicas backend observadas por HPA", "#2563eb", 3.5),
    ("backend_cpu_percent", "CPU backend: % respecto al request de 250m (objetivo 60%)", "#e76f17", None),
    ("backend_memory_mib", "Memoria agregada del backend (MiB)", "#0e9475", None),
):
    parts.append(chart(rows, key, title, color, maximum))
parts.append("<p class=note>La carga se ejecutó dentro de AWS contra el Service del backend, con login/bcrypt real y PostgreSQL. No se ajustan réplicas manualmente. El frontend no se somete a esta carga; su HPA permanece configurado.</p></section>")

parts.append("<section><h2>5. Terraform: validación y actualización</h2>")
for name in ('iac-backend-tests.txt', 'iac-frontend-tests.txt', 'iac-network-tests.txt', 'iac-database-tests.txt',
             'iac-tag-update-apply.txt', 'iac-tag-restore-apply.txt'):
    path = destination / name
    if path.exists():
        parts.append(f'<h3>{esc(name)}</h3><pre>{esc(redact(path.read_text()))}</pre>')
parts.append('<p><b>No se ejecutó la destrucción.</b> Los planes de borrado son una vista previa; no equivalen a una evidencia de terraform destroy exitoso.</p></section>')
parts.append("<section><h2>6. Archivos originales y comandos</h2><ul>")
for path in sorted(destination.rglob("*")):
    if path.is_file() and path.suffix in (".txt", ".json", ".csv", ".log", ".xml"):
        relative = path.relative_to(destination)
        parts.append(f'<li><a href="{esc(relative)}">{esc(relative)}</a></li>')
parts.append("</ul></section></html>")
(destination / "report.html").write_text("".join(parts))
print(destination / "report.html")
