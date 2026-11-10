# Despliegue desde cero en AWS Academy

Requisitos: AWS CLI v2, Terraform >= 1.16 y < 2 (usamos 1.16.2), kubectl compatible
con Kubernetes 1.35, Helm 3, Python >= 3.12 y Git. Activar el Lab y configurar sus
credenciales vigentes antes de comenzar.

Usar una copia limpia, sin estados, secretos ni configuración de otra cuenta.
Los comandos asumen región `us-east-1` y nombre `cloud-integrador-lab`.
Ejecutar por etapas y detenerse ante errores. Los recursos generan costos.

## 1. Descargar el proyecto

```bash
git clone https://github.com/2023JoshuaP/terraform-IaC-Stack.git
cd terraform-IaC-Stack
```

## Alternativa: ejecutar el despliegue completo

Después de clonar, con requisitos instalados y credenciales vigentes, obtener los
roles mediante el diagnóstico del paso 2. Luego ejecutar, sustituyendo los nombres:

```bash
python3 deployment/deploy-all.py \
  --region us-east-1 \
  --cluster-role NOMBRE_REAL_ROL_CLUSTER \
  --node-role NOMBRE_REAL_ROL_NODOS
```

Esta alternativa ejecuta los pasos siguientes; **no ejecutarlos también en paralelo**.
Solicita confirmación inicial y por cada plan. Agregar `--yes` solo para autorizar
creación y aplicación sin preguntas. Siempre rechaza eliminaciones/reemplazos.

Espera a Terraform (incluidos EKS y RDS), nodos Ready, componentes Helm, builds
secuenciales y respuestas HTTP del ALB antes del smoke test. La espera adicional
para nodos/HTTP es de 900 segundos; ajustar con `--ready-timeout 1800` si es necesario.
Terraform conserva sus propios límites de creación: no se cancela EKS a los 900 segundos.

Ante errores se detiene sin destruir lo creado. Tras corregir la causa, repetir el
comando con los mismos estados y secretos. Reutiliza imágenes ya publicadas y espera
Jobs existentes; si un Job falló o ya no existe sin haber publicado imagen, revisar
los logs y usar `--rebuild` para nuevos intentos. No recupera automáticamente inputs
RDS de redes destruidas ni credenciales expiradas. Si faltan permisos o hay ambigüedad
en roles se detiene. No instala herramientas, no clona y no cambia políticas IAM.

Planes (sensibles), metadata y resultado quedan en `.deployment/deploy-all-*/`.
No ejecutar sobre otra cuenta con estados de este despliegue ni desde varias máquinas
al mismo tiempo. El bloqueo del script protege solo esta copia local.

## 2. Confirmar cuenta y diagnosticar roles

```bash
aws sts get-caller-identity
python3 deployment/prepare-environment.py --region us-east-1
```

## 3. Preparar configuración

Reemplazar los nombres por roles de **su cuenta** que pasaron el diagnóstico.
En nuestro despliegue elegimos el rol específico `…LabEksClusterRole…` para el
clúster y `LabRole` para nodos. No elegir roles `denied`; si aparecen `unknown`,
revisar permisos antes de continuar. La simulación es parcial, no una garantía.

```bash
python3 deployment/prepare-environment.py \
  --region us-east-1 \
  --cluster-role NOMBRE_REAL_ROL_CLUSTER \
  --node-role NOMBRE_REAL_ROL_NODOS \
  --write
```

## 4. Crear ECR backend

```bash
terraform -chdir=stacks/backend init
terraform -chdir=stacks/backend validate
terraform -chdir=stacks/backend plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/backend apply -var-file=../../config/common.tfvars
```

## 5. Crear ECR frontend

```bash
terraform -chdir=stacks/frontend init
terraform -chdir=stacks/frontend validate
terraform -chdir=stacks/frontend plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/frontend apply -var-file=../../config/common.tfvars
```

## 6. Crear red y EKS

```bash
terraform -chdir=stacks/network init
terraform -chdir=stacks/network validate
terraform -chdir=stacks/network plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/network apply -var-file=../../config/common.tfvars
```

En cada `apply`, revisar el plan antes de confirmar con `yes`. Desde cero se
observaron 2 creaciones en backend, 2 en frontend y 22 en network, sin eliminaciones.
Mantener el Lab activo y esperar `Apply complete!` antes de continuar.

## 7. Conectar Kubernetes

```bash
aws eks update-kubeconfig \
  --region us-east-1 \
  --name cloud-integrador-lab \
  --alias cloud-integrador-lab

kubectl --context cloud-integrador-lab get nodes
```

Continuar cuando los dos nodos estén `Ready`.

## 8. Crear RDS

```bash
python3 deployment/prepare-database.py
terraform -chdir=stacks/database init
terraform -chdir=stacks/database validate
terraform -chdir=stacks/database plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/database apply -var-file=../../config/common.tfvars
```

Esperado desde cero: 5 creaciones, sin eliminaciones. No compartir los secretos
generados. Si el preparador informa inputs anteriores diferentes, detenerse y revisar.

## 9. Instalar ALB Controller y Metrics Server

```bash
bash deployment/install-platform.sh

kubectl --context cloud-integrador-lab -n kube-system \
  get deployments aws-load-balancer-controller metrics-server
```

Ambos deben mostrar `READY 1/1`.

## 10. Construir imágenes en AWS

```bash
python3 deployment/cloud-build.py backend
python3 deployment/wait-build.py backend
```

Solo cuando backend termine correctamente:

```bash
python3 deployment/cloud-build.py frontend
python3 deployment/wait-build.py frontend
```

Para observar los Jobs:

```bash
kubectl --context cloud-integrador-lab -n cloud-build get jobs,pods
```

Ambos Jobs deben terminar `Complete 1/1`. No desplegar si un build falla.

## 11. Desplegar aplicaciones

```bash
python3 deployment/deploy-apps.py --origin http://localhost

kubectl --context cloud-integrador-lab -n cloud-integrador \
  rollout status deployment/backend --timeout=600s

kubectl --context cloud-integrador-lab -n cloud-integrador \
  rollout status deployment/frontend --timeout=300s

kubectl --context cloud-integrador-lab -n cloud-integrador get ingress
```

## 12. Configurar el origen real y obtener el enlace

Esperar el hostname del ALB y ejecutar en la misma terminal:

```bash
kubectl --context cloud-integrador-lab -n cloud-integrador \
  wait --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' \
  ingress/cloud-integrador --timeout=600s

ALB_HOST="$(kubectl --context cloud-integrador-lab -n cloud-integrador \
  get ingress cloud-integrador \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"

python3 deployment/deploy-apps.py --origin "http://$ALB_HOST"

kubectl --context cloud-integrador-lab -n cloud-integrador \
  rollout status deployment/backend --timeout=600s

echo "http://$ALB_HOST"
```

Abrir el enlace mostrado. Usar solo datos ficticios: el piloto usa HTTP y restringe
el acceso a la IP detectada. No reutilizar enlaces de otros despliegues.

## 13. Verificar

```bash
kubectl --context cloud-integrador-lab -n cloud-integrador get pods,hpa,ingress
kubectl --context cloud-integrador-lab -n cloud-integrador top pods
python3 deployment/smoke-test.py "http://$ALB_HOST"
```

El smoke test crea un usuario sintético y comprueba página, becas, registro,
login, sesión y logout. En navegador, comprobar también inicio de sesión y perfil.

## Si cambia la IP pública

```bash
python3 deployment/update-access-ip.py
terraform -chdir=stacks/network plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/network apply -var-file=../../config/common.tfvars
```

Cerrar AWS o apagar el equipo no garantiza detener costos. Conservar los estados
y seguir el orden de limpieza al terminar.

## Limpieza (orden obligatorio)

1. Eliminar el Ingress con el controlador ALB todavía operativo:

   ```bash
   kubectl --context cloud-integrador-lab -n cloud-integrador \
     delete ingress cloud-integrador --wait=true --timeout=600s
   ```

2. Confirmar en AWS que se eliminaron el ALB y sus target groups; después eliminar
   los namespaces `cloud-integrador` y `cloud-build`.
3. Desactivar `deletion_protection` en los inputs de database y aplicar el cambio.
   Decidir si conservar el snapshot final (genera costos) o autorizar omitirlo.
4. Destruir primero database y después network, revisando cada plan:

   ```bash
   terraform -chdir=stacks/database destroy -var-file=../../config/common.tfvars
   terraform -chdir=stacks/network destroy -var-file=../../config/common.tfvars
   ```

5. Si se autoriza eliminar las imágenes ECR, configurar `force_delete=true` en los
   inputs de frontend/backend, aplicar el cambio y destruir ambos stacks con
   `-var-file=../../config/common.tfvars`.
6. Revisar snapshots, logs, ALB, ENI y otros recursos retenidos en AWS. No borrar
   estados antes de destruir, quitar finalizers manualmente ni eliminar roles del Lab.
