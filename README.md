# Cloud Integrador

Infraestructura y despliegue en AWS de **ProceedHub** (Spring Boot), **HamukHub**
(React/Vite) y PostgreSQL. Terraform administra cuatro stacks independientes;
las imágenes se construyen en EKS y se almacenan en ECR.

## Arquitectura

```text
Navegador → ALB → /      → Frontend (Nginx)
               → /api/* → Backend (Spring Boot) → RDS PostgreSQL privado
                          Aplicaciones en EKS
```

| Stack | Recursos |
|---|---|
| `network` | VPC, subredes, rutas, grupos de seguridad, EKS y nodos |
| `backend` | Repositorio ECR del backend |
| `frontend` | Repositorio ECR del frontend |
| `database` | RDS PostgreSQL, acceso de red y logs |

Cada stack tiene su propio estado. `database` recibe los IDs de `network` como
inputs explícitos. Los scripts de despliegue crean Deployments, Services, HPA e
Ingress; el controlador Kubernetes aprovisiona el ALB.

## Estructura

```text
config/         Valores comunes de Terraform (plantilla)
stacks/         network, backend, frontend y database
deployment/     Preparación de RDS, instalación, builds y despliegue
validation/     Pruebas, recuperación, carga e informes
```

## Requisitos

- Terraform >= 1.16, AWS CLI v2, kubectl, Helm, Python >= 3.12 y Git.
- Credenciales AWS vigentes y permisos para EKS, EC2, ECR, RDS y ELB.
- IP pública autorizada para la API EKS y la aplicación.
- En AWS Academy: roles existentes de clúster y nodos autorizados por el Lab.

No se necesita ejecutar Java, Node ni Docker localmente. Los builds y las
aplicaciones corren en AWS.

## Despliegue

Ejecutar desde la raíz del repositorio. Para un entorno nuevo:

1. Copiar `config/common.tfvars.example` a `config/common.tfvars` y las plantillas
   `terraform.tfvars.example` a `terraform.tfvars` de cada stack.
2. Configurar región, IPs y roles. En Academy usar `create_iam_roles=false` y los
   ARN de roles autorizados.
3. Inicializar, validar, revisar y aplicar `backend`, `frontend` y `network`.
4. Configurar kubectl, ejecutar `deployment/prepare-database.py` y aplicar
   `database` con los inputs generados.
5. Instalar componentes con `deployment/install-platform.sh`.
6. Construir backend y frontend con `deployment/cloud-build.py`, secuencialmente,
   comprobando que cada Job termine correctamente.
7. Desplegar con `deployment/deploy-apps.py`, obtener el hostname ALB y actualizar
   el origen de la aplicación.
8. Comprobar disponibilidad con `deployment/smoke-test.py`.

Ejemplo del ciclo Terraform para un stack:

```bash
aws sts get-caller-identity
terraform -chdir=stacks/backend init
terraform -chdir=stacks/backend validate
terraform -chdir=stacks/backend plan -var-file=../../config/common.tfvars
terraform -chdir=stacks/backend apply -var-file=../../config/common.tfvars
```

Los comandos de construcción y ejecución están en la
[guía de despliegue](deployment/README.md).
No aplicar desde un estado vacío si los recursos ya existen: recuperar o migrar
el estado correspondiente primero.

## Validación

Los stacks incluyen tests con AWS simulado; inicializar cada stack antes:

```bash
terraform -chdir=stacks/network test
terraform -chdir=stacks/backend test
terraform -chdir=stacks/frontend test
terraform -chdir=stacks/database test
```

Para un entorno desplegado:

```bash
python3 deployment/smoke-test.py "http://HOSTNAME_ALB"
kubectl --context cloud-integrador-lab -n cloud-integrador get pods,hpa,ingress
kubectl --context cloud-integrador-lab -n cloud-integrador top pods --containers
```

Sustituir `HOSTNAME_ALB` por el hostname actual. Los scripts de `validation/`
incluyen pruebas de código, recuperación y carga k6. Algunos usan nombres o URL
del piloto: revisarlos antes de ejecutarlos en otro entorno. Recuperación y carga
tienen efectos reales sobre los workloads.

## Seguridad y costos

- No versionar credenciales, secretos, estados, planes ni valores locales.
  Las plantillas y `.terraform.lock.hcl` sí se versionan.
- Los estados son locales y contienen datos sensibles. Para operar desde varios
  equipos, migrar a un backend remoto cifrado con bloqueo y una clave por stack.
- El piloto usa HTTP restringido por IP, roles amplios del Lab y builds
  privilegiados. No usar datos reales ni tomarlo como configuración de producción.
- RDS es Single-AZ. El HPA escala pods; no hay autoscaler de nodos instalado.
- Los builds son remotos y se lanzan manualmente; GitHub Actions sigue pendiente.
- EKS, EC2, RDS, ALB, almacenamiento y recursos retenidos generan costos aunque no
  se abra la aplicación.

## Limpieza

Eliminar primero el Ingress y confirmar la retirada del ALB con el controlador
activo. Después borrar workloads, desactivar/aplicar la protección de RDS y
destruir `database` antes de `network`. Destruir los ECR solo tras aprobar el
borrado de imágenes. Los snapshots retenidos siguen generando costos.

Procedimiento: [limpieza del despliegue](deployment/README.md#limpieza-orden-obligatorio).

## Documentación

- [Construcción y despliegue](deployment/README.md)
- [Validación y evidencias](validation/README.md)

## Aplicaciones

- Backend: [Natzgun/ProceedHub](https://github.com/Natzgun/ProceedHub)
- Frontend: [Natzgun/HamukHub](https://github.com/Natzgun/HamukHub)
