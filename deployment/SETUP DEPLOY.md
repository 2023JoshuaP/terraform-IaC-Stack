# Piloto completamente ejecutado en AWS

Guía paso a paso para compartir: [despliegue desde cero en otra cuenta](INICIO_OTRA_CUENTA.md).

## Qué ocurre

1. Terraform crea ECR, EKS y RDS en los cuatro stacks independientes.
2. Jobs temporales en EKS descargan commits concretos de los repositorios públicos.
3. BuildKit construye las imágenes, ejecutando pruebas durante el build, y las sube a ECR.
4. Los pods de aplicación se ejecutan en EKS, conectados a PostgreSQL privado en RDS.
5. Un Ingress crea un ALB público limitado a los CIDR configurados en network.

No se necesita ejecutar Docker ni Java en el equipo local. AWS CLI, kubectl,
Terraform, Python y Helm solo envían instrucciones de administración.

## Excepción de seguridad del Learner Lab

El Lab no permite crear roles IAM normales. El piloto usa el rol EKS de clúster
preexistente y `LabRole` preexistente para los nodos. Se verificaron confianza EC2,
permisos EKS, ECR y balanceadores; no se modificaron esos roles.

El controlador ALB y los Jobs usan `hostNetwork` y credenciales de IMDS del nodo.
Los builds son privilegiados y `LabRole` tiene permisos amplios. **Solo para un
laboratorio aislado con código confiable.** En producción usar roles por ServiceAccount,
IRSA/Pod Identity, builders aislados y permisos mínimos. No hay credenciales del
usuario dentro de los manifiestos ni publicadas en Git.

## Preparación dinámica por cuenta (AWS Academy)

Desde la raíz, con credenciales vigentes, ejecutar primero solo el diagnóstico:

```bash
python3 deployment/prepare-environment.py --region us-east-1
```

Detecta cuenta, IP, roles con confianza EKS/EC2 y simula grupos básicos de permisos
de arranque, lectura/publicación ECR y controlador ALB. No crea recursos ni cambia
IAM. `allowed` significa únicamente que esas acciones pasaron la simulación;
**no es una auditoría completa**. No garantiza condiciones de confianza, permisos
de todas las API, SCP, cuotas ni disponibilidad. `denied` impide seleccionar el rol;
`unknown` significa que faltó contexto o acceso a la simulación, no que tenga permiso.

Si existe exactamente un candidato comprobado por función, preparar los inputs:

```bash
python3 deployment/prepare-environment.py --region us-east-1 --write
```

Si hay varios, elegir explícitamente los nombres/ARN mostrados:

```bash
python3 deployment/prepare-environment.py --region us-east-1 \
  --cluster-role NOMBRE_ROL_CLUSTER --node-role NOMBRE_ROL_NODOS --write
```

Si Academy impide simular, revisar los permisos con el administrador. Solo después
de esa revisión se puede aceptar la incertidumbre con `--allow-unverified`, eligiendo
explícitamente cada rol no verificado. Esto **no concede permisos ni evita bloqueos**.

Al escribir, genera las plantillas locales faltantes, configura roles existentes,
región, dos zonas disponibles para una red nueva y ambos accesos `/32`. Preserva otros
valores y respalda archivos previos en `.deployment/environment-*/`. No aplica
Terraform; revisar siempre el plan. Bloquea estados con ARN de otra cuenta y cambios
de roles/región de network desplegado; estas comprobaciones no sustituyen una revisión
del estado. Para otra cuenta usar una copia de trabajo independiente **sin copiar
estados, secretos ni inputs privados**. Nunca borrar estados de recursos activos.

No genera los inputs de RDS antes de tener red: luego usar `prepare-database.py`.
Si quedan inputs de una red destruida, ese script se detendrá para revisión.
El preparador no reconstruye aplicaciones ni configura credenciales automáticamente.

## Actualizar la IP pública autorizada

Si cambia la conexión del operador, detectar la IPv4 pública mediante el servicio
HTTPS de AWS y actualizar los dos CIDR en `stacks/network/terraform.tfvars`:

```bash
python3 deployment/update-access-ip.py --check
python3 deployment/update-access-ip.py
terraform -chdir=stacks/network plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/network apply -var-file=../../config/common.tfvars
```

El script solo modifica el archivo local; no requiere credenciales AWS ni aplica
Terraform. Conserva los otros valores y sustituye **ambas listas completas** por
la IP actual `/32`; no usar sin revisar si hay varios operadores autorizados.
Necesita las dos asignaciones en una línea y se detiene ante formatos no previstos.
La IP detectada es la salida pública del equipo (o de su VPN/proxy), no la del ALB.
Ejecutarlo con la conexión desde la que se administrará EKS y se abrirá la página.

## Ejecución manual después de aplicar network

Todos los comandos parten desde `cloud-integrador/`. No lanzar construcciones simultáneas
en el node group pequeño; esperar la terminación de cada Job.

```bash
aws eks update-kubeconfig --region us-east-1 --name cloud-integrador-lab --alias cloud-integrador-lab
kubectl --context cloud-integrador-lab get nodes

python3 deployment/prepare-database.py
terraform -chdir=stacks/database plan -var-file=../../config/common.tfvars
# Revisar antes de crear RDS:
terraform -chdir=stacks/database apply -var-file=../../config/common.tfvars

bash deployment/install-platform.sh
python3 deployment/cloud-build.py backend
```

Si Helm no está en PATH, se puede especificar una ruta mediante `HELM=/ruta/helm`.
El script cloud-build imprime el nombre del Job y el comando de logs. Comprobar que
terminó exitosamente antes de continuar con frontend:

```bash
kubectl --context cloud-integrador-lab -n cloud-build get jobs,pods
python3 deployment/cloud-build.py frontend
```

Los registros no sensibles de imagen/commit/Job quedan en `.deployment/*-build.json`.
Los tokens ECR se obtienen dentro de AWS, se guardan solo en un volumen efímero del Job
y desaparecen al eliminar el pod. Los Jobs terminados tienen TTL de diez minutos.

Cuando ambas imágenes estén publicadas y RDS disponible:

```bash
python3 deployment/deploy-apps.py --origin http://localhost
kubectl --context cloud-integrador-lab -n cloud-integrador rollout status deployment/backend --timeout=600s
kubectl --context cloud-integrador-lab -n cloud-integrador rollout status deployment/frontend --timeout=300s
kubectl --context cloud-integrador-lab -n cloud-integrador get ingress
```

El origen localhost es solo de bootstrap, hasta conocer el hostname del ALB. Después:

```bash
ALB_HOST="$(kubectl --context cloud-integrador-lab -n cloud-integrador get ingress cloud-integrador -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
python3 deployment/deploy-apps.py --origin "http://$ALB_HOST"
kubectl --context cloud-integrador-lab -n cloud-integrador rollout status deployment/backend --timeout=600s
curl --fail "http://$ALB_HOST/api/scholarships/get_all"
```

Se usan imágenes por digest, no `latest`. La URL sirve frontend y API en el mismo origen:
Vite se construye con `VITE_API_URL=/api`. Las comprobaciones backend usan la ruta real
`/api/scholarships/get_all`; liveness TCP no sustituye un endpoint Actuator.

Prueba funcional externa (crea un usuario sintético, no imprime contraseñas ni tokens):

```bash
python3 deployment/smoke-test.py "http://$ALB_HOST"
```

## Secretos

`prepare-database.py` genera `.deployment/secrets.json` con permisos 600, sin mostrar
contraseñas. Genera también `stacks/database/deployment.auto.tfvars.json` privado,
con inputs de red, contraseña RDS y snapshot final. No sobrescribe secretos existentes.
Estos archivos están ignorados por Git. El estado RDS también contiene la contraseña.
Conservarlos seguros: no pegarlos en el chat ni subirlos al repositorio.

## Límites de esta demostración

- HTTP restringido a la IP del laboratorio: **solo usuarios y datos sintéticos**.
  Añadir HTTPS/ACM antes de datos reales.
- Sin GitHub Actions aún: los builds son remotos, pero se lanzan manualmente.
- HPA escala pods, no nodos. El node group no tiene Cluster Autoscaler.
- RDS Single-AZ; no es alta disponibilidad.
- Logs de aplicaciones mediante kubectl; CloudWatch de control plane y PostgreSQL.
  Container Insights no está activado por defecto.
- EKS, dos EC2, RDS, ALB, IPv4, discos, imágenes y logs consumen créditos aunque
  no abras la aplicación. No dejarlo encendido sin necesidad.

## Limpieza (orden obligatorio)

1. Eliminar el Ingress **manteniendo operativo el controlador ALB** y confirmar que AWS
   borró el balanceador y target groups:

   ```bash
   kubectl --context cloud-integrador-lab -n cloud-integrador delete ingress cloud-integrador --wait=true --timeout=600s
   ```

2. Eliminar los namespaces `cloud-integrador` y `cloud-build` cuando ya no se necesiten.
3. En los inputs de database, desactivar `deletion_protection` y aplicar ese cambio.
   Confirmar si conservar el snapshot final (seguirá cobrando) o aprobar omitirlo.
4. Ejecutar `terraform destroy` en database, siempre con el archivo común.
5. Ejecutar `terraform destroy` en network con el archivo común.
6. Si se aprueba eliminar imágenes, aplicar `force_delete=true` en frontend/backend
   y destruir esos stacks. No borrar los archivos de estado antes de destruir.
7. Revisar snapshots, logs, ALB/ENI y recursos retenidos en AWS. No quitar finalizers
   manualmente ni eliminar roles preexistentes del Lab.
