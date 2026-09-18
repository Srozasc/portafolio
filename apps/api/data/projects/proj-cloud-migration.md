---
slug: proj-cloud-migration
title_es: Migración de monolito a microservicios en AWS EKS
title_en: Monolith-to-microservices migration to AWS EKS
year: 2023
role_es: Cloud Architect
role_en: Cloud Architect
client: E-commerce regional
tags:
  - terraform
  - aws
  - kubernetes
  - docker
  - ci-cd
  - devops
stack_es:
  - AWS (EKS, RDS Aurora, ElastiCache Redis, S3, CloudFront, ALB)
  - Kubernetes 1.27 + Helm + ArgoCD (GitOps)
  - Terraform 1.5 (módulos reutilizables, remote state en S3 + DynamoDB)
  - Docker + multi-stage builds
  - GitHub Actions (CI) + ArgoCD (CD)
  - Datadog + Prometheus + Grafana (observabilidad)
stack_en:
  - AWS (EKS, RDS Aurora, ElastiCache Redis, S3, CloudFront, ALB)
  - Kubernetes 1.27 + Helm + ArgoCD (GitOps)
  - Terraform 1.5 (reusable modules, remote state in S3 + DynamoDB)
  - Docker + multi-stage builds
  - GitHub Actions (CI) + ArgoCD (CD)
  - Datadog + Prometheus + Grafana (observability)
summary_es: "Migración de monolito on-prem a microservicios en AWS EKS. Zero downtime, 60% reducción de costos operativos."
summary_en: "Migration from on-prem monolith to microservices on AWS EKS. Zero downtime, 60% reduction in operating costs."
impact_es:
  - "Zero downtime en cutover (estrategia strangler-fig con feature flags)"
  - "Costos operativos reducidos 60% (USD 28K → USD 11K/mes)"
  - "Deploy frequency: 1/semana → 12/día"
  - "MTTR: 2 horas → 18 minutos"
impact_en:
  - "Zero-downtime cutover (strangler-fig with feature flags)"
  - "Operating costs cut 60% (USD 28K → USD 11K/month)"
  - "Deploy frequency: 1/week → 12/day"
  - "MTTR: 2 hours → 18 minutes"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

El cliente tenía un monolito PHP/MySQL on-prem que llevaba casi diez años en
producción: 380K líneas de código, un único deploy mensual que generaba
incidentes recurrentes, y una infraestructura subdimensionada para los
picos de tráfico del Black Friday. El negocio necesitaba escalar de forma
elástica, mejorar el time-to-market y dejar de pagar por capacidad ociosa el
90% del mes. La decisión estratégica fue migrar a microservicios en EKS,
pero el constraint duro era cero downtime: cualquier minuto caído se medía
en pérdida de revenue directa.

## Decisiones técnicas

Adopté la estrategia strangler-fig: en vez de un big-bang rewrite, identifiqué
los cinco bounded contexts de mayor carga (catálogo, carrito, checkout,
pagos, fulfillment) y los extraje uno a uno detrás de un API Gateway que
enrutaba por feature flag. Esto nos permitió mantener el monolito sirviendo
tráfico mientras cada servicio nuevo se dogfooded internamente antes de
apuntar producción. La infra se gestiona con Terraform: módulos reutilizables
para EKS, RDS, networking y un módulo de service-template que cualquier
equipo puede consumir para crear un servicio nuevo en menos de una hora.

Para el CD usamos GitOps con ArgoCD: cada PR mergeada a `main` actualiza un
chart de Helm versionado en el repo de infra, ArgoCD lo reconcilia contra el
cluster y los rollouts son automáticos con health checks + análisis de
Datadog. La base de datos se migró con AWS DMS en réplica continua antes del
cutover final; cuando llegó el switch, una transacción de blue/green a nivel
de Route 53 movió el tráfico en menos de 60 segundos con rollback inmediato
si las métricas se degradaban. Multi-AZ en todo (EKS nodes en tres AZs,
Aurora con réplicas cross-AZ) y backups automatizados con PITR a 35 días.

## Lecciones aprendidas

La lección más valiosa fue la regla del "if it hurts, do it more often": los
primeros dos servicios extraídos tardaron casi un mes cada uno porque el
pipeline de CI/CD no estaba preparado para despliegues independientes, y
resolver cada blocker era archaeology. Invertimos dos semanas en estabilizar
el template de servicio (Dockerfile multi-stage, chart de Helm, manifests de
ArgoCD, dashboard y alertas preconfiguradas) y a partir del tercer servicio
los nuevos tardaban dos días. La segunda lección es que Kubernetes no es
gratis: dedicamos las primeras semanas a un runbook de troubleshooting de
pods (evicted, OOMKilled, imagePullBackOff) que después compartimos con
todos los equipos, porque sin ese runbook el cluster se convierte en un
generador de tickets. Por último, la observabilidad tuvo que venir antes del
tráfico real: configurar Distributed Tracing con OpenTelemetry desde el día
uno nos ahorró semanas de "ghost bugs" que aparecían solo en producción.
