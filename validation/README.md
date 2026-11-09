# Validación y capturas

Ejecutar desde `cloud-integrador/`. Las aplicaciones y los tests corren en AWS;
Python local solamente coordina comandos y descarga evidencias.

## Evidencias conservadas

La ejecución actual se encuentra en `evidence/run-20261109T051417Z/`.
`report.html` reúne resultados y gráficas; abrirlo en el navegador para capturarlo
o imprimirlo como PDF. No representa una captura de la consola AWS.

```bash
python3 validation/report.py
```

Archivos importantes:

- `baseline-functional.txt`: prueba externa frontend → backend → PostgreSQL.
- `tests-backend/summary.json`: 35 pruebas aprobadas y cobertura JaCoCo.
- `tests-frontend/summary.json`: 4 pruebas aprobadas; sin medición de cobertura.
- `recovery-result.json`, `recovery-before.txt`, `recovery-after.txt`: pod
  eliminado y reemplazo con distinto UID; recuperación observada de 28,47 s.
- `load-result.json`, `load-k6-summary.json`: resultados de carga, cuando finalice.
- `load-timeseries.csv`: CPU, memoria y réplicas observadas durante carga y reposo.
- `iac-*-tests.txt`: tests Terraform con proveedor simulado, no crean recursos.
- `iac-tag-update-apply.txt`, `iac-tag-restore-apply.txt`: actualización real y
  reversible de una etiqueta ECR, sin reemplazar la aplicación.
- `iac-*-destroy-PLAN-ONLY.txt`: **solo planificación**, no prueba de eliminación.
- `monitor-cloudwatch-streams.txt`: recepción de logs de control de EKS.

Se conservan también los intentos fallidos de descarga de Gradle; la ejecución
exitosa usó Gradle 9.1.0 preinstalado, versión igual al wrapper del repositorio.

## Orden sugerido de capturas

1. Aplicación en el navegador y prueba funcional (`baseline-functional.txt`).
2. Consola AWS, región **N. Virginia / us-east-1**: EKS activo y dos nodos;
   ECR con imágenes; RDS disponible con acceso público desactivado.
3. Pruebas y cobertura del informe. El HTML original de Gradle está bajo
   `tests-backend/tests-backend-20261109052048/reports/tests/test/index.html`.
4. Recuperación: estado anterior, eliminación y estado posterior. No afirmar
   cero interrupciones: una sola réplica no ofrece alta disponibilidad.
5. Gráficas de carga y HPA del informe, junto con los umbrales k6.
6. Actualización Terraform y restauración; planificación de destrucción
   claramente identificada como no ejecutada.
7. CloudWatch → Log groups → `/aws/eks/cloud-integrador-lab/cluster`.
   Los logs de aplicación están en Kubernetes; no se instaló un colector
   de logs de aplicación ni Container Insights.

No capturar archivos `.deployment/secrets.json`, `terraform.tfstate`,
`*.tfvars.json` privados, secretos Kubernetes ni credenciales AWS Academy.

## Repetición (tiene efectos reales y consume créditos)

```bash
python3 validation/snapshot.py --prefix final
python3 validation/test-apps.py backend
python3 validation/test-apps.py frontend
python3 validation/recovery.py
python3 validation/load-test.py
python3 validation/report.py
```

`recovery.py` elimina un único pod backend. `load-test.py` crea un usuario
sintético y genera hasta 16 login/s durante tres minutos desde un Job EKS,
sin cambiar manualmente las réplicas; observa después la reducción automática.
La carga interna no mide latencia de Internet ni del ALB.

`iac.py` valida los cuatro stacks, ejecuta sus tests, comprueba planes sin
cambios, aplica/restaura una etiqueta ECR y genera planes de destrucción.
No ejecuta `terraform destroy`. La eliminación real y CI/CD siguen pendientes.
