# Cloud Integrador

Infraestructura y despliegue en AWS de **ProceedHub** (Spring Boot), **HamukHub**
(React/Vite) y PostgreSQL. Terraform administra cuatro stacks independientes;
las imágenes se construyen en EKS y se almacenan en ECR. Incluye un script para
automatizar el despliegue en AWS Academy y una guía para ejecutarlo por etapas.

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
deployment/     Guía, automatización, preparación, builds y despliegue
validation/     Pruebas, recuperación, carga e informes
```

## Requisitos

- Terraform >= 1.16 y < 2, AWS CLI v2, kubectl compatible con Kubernetes 1.35,
  Helm 3, Python >= 3.12 y Git en Linux/Bash o WSL.
- Credenciales AWS vigentes y permisos para EKS, EC2, ECR, RDS y ELB.
- IP pública autorizada para la API EKS y la aplicación.
- En AWS Academy: roles existentes de clúster y nodos autorizados por el Lab.

No se necesita ejecutar Java, Node ni Docker localmente. Los builds y las
aplicaciones corren en AWS.

## Despliegue

Activar el Lab, configurar credenciales vigentes y usar un clon limpio para cada
cuenta. Ejecutar desde la raíz del repositorio:

```bash
aws sts get-caller-identity
python3 deployment/prepare-environment.py --region us-east-1
```

Elegir roles de la cuenta que pasaron el diagnóstico y sustituir los nombres:

```bash
python3 deployment/deploy-all.py \
  --region us-east-1 \
  --cluster-role NOMBRE_REAL_ROL_CLUSTER \
  --node-role NOMBRE_REAL_ROL_NODOS
```

El script prepara los inputs, aplica los cuatro stacks, conecta Kubernetes,
instala ALB Controller y Metrics Server, construye ambas imágenes secuencialmente,
despliega las aplicaciones y ejecuta el smoke test. Al terminar muestra el enlace.

- Espera la creación de EKS/RDS, nodos `Ready`, rollouts, builds y HTTP del ALB.
- Solicita confirmación inicial y por cada plan; `--yes` permite aplicar sin preguntas.
- Rechaza planes con eliminaciones o reemplazos y se detiene ante errores, sin
  destruir automáticamente lo creado.
- `--ready-timeout 1800` amplía la espera de nodos/HTTP; Terraform mantiene sus
  propios límites de creación.
- No instala herramientas, configura credenciales ni modifica políticas IAM.

La simulación IAM es parcial: no garantiza todas las acciones, SCP ni cuotas.
Ante ambigüedad o permisos insuficientes, revisar el diagnóstico antes de continuar.

Para el procedimiento manual y la recuperación de intentos fallidos, consultar
[SETUP DEPLOY](deployment/SETUP%20DEPLOY.md). No ejecutar el flujo manual y el
automático en paralelo. No copiar estados, secretos ni inputs de otra cuenta, ni
aplicar desde un estado vacío sobre recursos existentes.

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
- `.deployment/` contiene secretos y metadatos privados; el orquestador guarda
  planes sensibles y el resultado en `.deployment/deploy-all-*/`. No publicarlos,
  ni las carpetas locales de documentación o evidencias.
- Los estados son locales y contienen datos sensibles. Para operar desde varios
  equipos, migrar a un backend remoto cifrado con bloqueo y una clave por stack.
- El piloto usa HTTP restringido por IP, roles amplios del Lab y builds
  privilegiados. El builder y el controlador ALB usan credenciales del nodo mediante
  IMDS y `hostNetwork`. Solo para laboratorio con código confiable y datos ficticios;
  no es una configuración de producción.
- RDS es Single-AZ. El HPA escala pods; no hay autoscaler de nodos instalado.
- Los builds son remotos, lanzados por el orquestador o por comandos individuales;
  no hay pipeline de GitHub Actions.
- EKS, EC2, RDS, ALB, almacenamiento y recursos retenidos generan costos aunque no
  se abra la aplicación.

## Limpieza

Eliminar primero el Ingress y confirmar la retirada del ALB con el controlador
activo. Después borrar workloads, desactivar/aplicar la protección de RDS y
destruir `database` antes de `network`. Destruir los ECR solo tras aprobar el
borrado de imágenes. Los snapshots retenidos siguen generando costos.

Procedimiento: [limpieza del despliegue](deployment/SETUP%20DEPLOY.md#limpieza-orden-obligatorio).

## Documentación

- [Construcción y despliegue](deployment/SETUP%20DEPLOY.md)
- [Validación y evidencias](validation/README.md)

## Aplicaciones

- Backend: [Natzgun/ProceedHub](https://github.com/Natzgun/ProceedHub)
- Frontend: [Natzgun/HamukHub](https://github.com/Natzgun/HamukHub)
