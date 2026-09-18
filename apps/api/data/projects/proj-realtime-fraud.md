---
slug: proj-realtime-fraud
title_es: Detección de fraude en tiempo real
title_en: Real-time fraud detection
year: 2025
role_es: Senior Backend Engineer
role_en: Senior Backend Engineer
client: Fintech regional
tags:
  - python
  - kafka
  - flink
  - aws
  - real-time
  - fraud-detection
stack_es:
  - Python 3.11 + Apache Flink (PyFlink)
  - Apache Kafka (transactional events, 8K msg/s peak)
  - AWS Managed Streaming for Kafka (MSK)
  - Redis (feature store online + rule cache)
  - DynamoDB (eventos confirmados, TTL 90 días)
  - Terraform + Helm + ArgoCD
  - Grafana + Prometheus + alerting en PagerDuty
stack_en:
  - Python 3.11 + Apache Flink (PyFlink)
  - Apache Kafka (transactional events, 8K msg/s peak)
  - AWS Managed Streaming for Kafka (MSK)
  - Redis (online feature store + rule cache)
  - DynamoDB (confirmed events, 90-day TTL)
  - Terraform + Helm + ArgoCD
  - Grafana + Prometheus + PagerDuty alerting
summary_es: "Sistema de detección de fraude en tiempo real. Detecta anomalías en < 200ms con FPR < 0.1%."
summary_en: "Real-time fraud detection system. Detects anomalies in < 200ms with FPR < 0.1%."
impact_es:
  - "Latencia end-to-end < 200 ms (p95) y < 350 ms (p99)"
  - "False positive rate < 0.1% sobre 2.1M transacciones evaluadas"
  - "Recall 92% sobre los casos confirmados por backoffice"
  - "Ahorro estimado de USD 420K/año en fraude prevenido"
impact_en:
  - "End-to-end latency < 200 ms (p95), < 350 ms (p99)"
  - "False positive rate < 0.1% over 2.1M scored transactions"
  - "92% recall on backoffice-confirmed fraud"
  - "Estimated USD 420K/year savings on prevented fraud"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

La fintech procesaba un pico de 8K transacciones por segundo en horario
comercial y el sistema legacy de reglas (basado en un motor de Drools batch
sobre un data warehouse con 20 minutos de lag) bloqueaba transacciones
legítimas y se demoraba en detectar patrones nuevos. El negocio necesitaba
sub-segundo de latencia y un sistema que aprendiera de los casos confirmados
por el equipo de fraude, sin caer en el clásico problema de "reglas estáticas
que se vencen a la semana". Diseñé e implementé el pipeline de scoring en
tiempo real y el sistema de feedback que cierra el loop entre detección y
etiquetado.

## Decisiones técnicas

El corazón del sistema es un job de Apache Flink (PyFlink) corriendo en un
cluster dedicado sobre Kubernetes, que consume eventos de Kafka, enriquece
cada transacción con features en Redis (velocity por tarjeta, merchant
risk score, device fingerprint), y produce un score + decisión en menos de
200 ms end-to-end. El scoring combina tres capas: (1) reglas determinísticas
para casos conocidos (lista negra de BINs, montos anómalos por merchant),
(2) un modelo XGBoost servido vía SageMaker con cache local de predicciones
recientes, y (3) un modelo no supervisado (Isolation Forest) que detecta
anomalías multivariadas. Las tres capas votan con pesos ajustables vía
feature flags, lo que nos permite hacer rollback de una capa en menos de un
minuto si degrada la métrica de negocio.

El loop de aprendizaje es lo que diferencia este sistema de uno naive: cada
decisión queda en Kafka con un ID de transacción, y cuando el backoffice de
fraude confirma o descarta el caso (típicamente en T+1), el evento de
feedback actualiza un dataset etiquetado que dispara un reentrenamiento
semanal del modelo. Para evitar feedback poisoning (un agente deshabilita
fraudes legítimos), las etiquetas se someten a un consenso de dos analistas
antes de entrar al dataset de training. Toda la topología de Flink, los
jobs de feedback y los rulesets se versionan en Git y se despliegan por
ArgoCD; los rulesets críticos pueden actualizarse con hot-reload vía un
endpoint HTTP sin reiniciar el job.

## Lecciones aprendidas

La primera lección fue que en sistemas de fraude, la latencia y la precisión
están en tensión permanente: cada modelo más complejo que probamos sumaba
20-50 ms, y ese costo se paga en cada transacción. La solución no fue
"sacá features" sino distribuirlas: las features baratas (counters en Redis)
viajan en el path caliente, y las costosas (joins sobre historial completo)
se precalculan y se sirven como lookup. La segunda lección es que los falsos
positivos duelen más que los falsos negativos: bloquear una transacción
legítima erosiona la confianza del cliente y genera costos operativos
(llamadas al contact center, contracargos). Optimizamos duro el FPR incluso
a costa de recall durante los primeros meses, y solo lo subimos cuando el
sistema demostró que podía mantenerlo bajo control. Por último, la
observabilidad no es opcional cuando estás bloqueando dinero en tiempo real:
un dashboard con las métricas top (FPR, recall estimado, latencia p95/p99)
delante de todo el equipo nos permitió detectar degradaciones en minutos, no
en días.
