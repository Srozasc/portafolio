---
slug: proj-data-pipeline
title_es: Pipeline de datos en tiempo real
title_en: Real-time data pipeline
year: 2024
role_es: Tech Lead
role_en: Tech Lead
client: Banco X (NDA)
tags:
  - python
  - aws
  - kafka
  - spark
  - data-engineering
  - senior
stack_es:
  - Python 3.11
  - AWS (Kinesis Data Streams, Lambda, S3, Glue Catalog)
  - Apache Kafka + Kafka Connect
  - Apache Spark Structured Streaming
  - Terraform + GitHub Actions
  - Datadog (metrics + logs + APM)
stack_en:
  - Python 3.11
  - AWS (Kinesis Data Streams, Lambda, S3, Glue Catalog)
  - Apache Kafka + Kafka Connect
  - Apache Spark Structured Streaming
  - Terraform + GitHub Actions
  - Datadog (metrics + logs + APM)
summary_es: "Pipeline de datos en tiempo real procesando 50M eventos/día con latencia < 5s. Redujo costos de infraestructura 40%."
summary_en: "Real-time data pipeline processing 50M events/day with < 5s latency. Reduced infrastructure costs 40%."
impact_es:
  - "Latencia reducida de 30 min a < 5 s (p99)"
  - "Ahorro de ~USD 15K/mes en infraestructura"
  - "Procesa 50M eventos/día con 99.95% uptime"
  - "Onboarding de nuevas fuentes de datos: de 2 semanas a 2 días"
impact_en:
  - "Latency cut from 30 min to < 5 s (p99)"
  - "~USD 15K/month infra savings"
  - "Processes 50M events/day at 99.95% uptime"
  - "New data source onboarding: 2 weeks → 2 days"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

El banco corría un batch nocturno en Hadoop que tardaba más de 30 minutos en
consolidar las transacciones del día y alimentar los modelos de fraude y los
reportes regulatorios. El negocio necesitaba decisiones casi en tiempo real
(bloqueo de operaciones sospechosas, alertas al cliente) y el cuello de botella
estaba en la capa de ingestión más que en los modelos en sí. Tomé el
leadership técnico de la migración: definir la arquitectura target, elegir el
stack, coordinar un squad de cuatro personas y acompañar al equipo de
Data Platform del banco durante la entrega.

## Decisiones técnicas

Optamos por una arquitectura lambda-lite: Kinesis Data Streams como buffer de
ingesta (ofrecía el SLA que necesitábamos sin la complejidad operativa de
Kafka puro), Kafka como bus interno para desacoplar producers de consumers, y
Spark Structured Streaming para los jobs de enriquecimiento y agregación. Todo
el ciclo de vida de la infraestructura se gestiona con Terraform y los
despliegues pasan por GitHub Actions con promoción manual entre environments
(dev → staging → prod). Para los schemas usamos Avro + Glue Schema Registry, lo
que nos dio compatibilidad forward/backward sin tener que mantener un
schema server separado.

Un punto clave fue modelar explícitamente el "late data" y los reintentos: el
pipeline tiene tres capas de checkpointing (Kinesis, Kafka offsets, Spark
checkpoint store en S3) y una DLQ dedicada que nos permite reprocesar batches
sin tocar el flujo principal. Esto fue la diferencia entre tener un sistema
que funciona en el demo y uno que funciona el lunes a las 9 AM.

## Lecciones aprendidas

La lección más cara fue subestimar el costo de Kinesis a 50M eventos/día con
shards fijos: terminamos pagando por capacidad ociosa por el burst de las
primeras horas de la mañana. La migración a un modelo on-demand + auto scaling
nos bajó la factura un 40% en tres meses. La segunda lección es que "tiempo
real" en finanzas no es un SLA técnico, es un SLA de negocio: tuvimos que
involucrar a Compliance desde el día uno para definir qué latencia era
aceptable por tipo de evento (no todo necesita < 1 s, y forzar esa latencia en
eventos batch-friendly multiplica el costo por cinco). Por último, la
documentación operacional (runbooks, dashboards, alertas accionables) pesó
más que el código mismo: el sistema es operado por un equipo distinto al que
lo construyó.
