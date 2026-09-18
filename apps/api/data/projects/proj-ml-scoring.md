---
slug: proj-ml-scoring
title_es: Scoring crediticio en producción
title_en: Credit scoring in production
year: 2023
role_es: ML Engineer
role_en: ML Engineer
client: Banco X (NDA)
tags:
  - python
  - ml
  - mlops
  - aws-sagemaker
  - kafka
  - terraform
stack_es:
  - Python 3.10 + scikit-learn + XGBoost
  - AWS SageMaker (training + endpoint multi-model)
  - Apache Kafka (features en tiempo real)
  - Feast (feature store online/offline)
  - MLflow (tracking + model registry)
  - Terraform + GitHub Actions
  - Evidently AI (drift detection)
stack_en:
  - Python 3.10 + scikit-learn + XGBoost
  - AWS SageMaker (training + multi-model endpoint)
  - Apache Kafka (real-time features)
  - Feast (online/offline feature store)
  - MLflow (tracking + model registry)
  - Terraform + GitHub Actions
  - Evidently AI (drift detection)
summary_es: "Modelo de scoring crediticio en producción. AUC 0.87, latencia < 100ms, 2M predicciones/día."
summary_en: "Credit scoring model in production. AUC 0.87, < 100ms latency, 2M predictions/day."
impact_es:
  - "AUC 0.87 sobre holdout, AUC 0.84 monitorizado en producción"
  - "Latencia p99 < 100 ms en endpoint multi-modelo"
  - "2M predicciones/día sostenidas en producción"
  - "Tiempo de reentrenamiento: 8 h → 1.5 h con pipeline paralelo"
impact_en:
  - "AUC 0.87 on holdout, AUC 0.84 monitored in production"
  - "p99 latency < 100 ms on multi-model endpoint"
  - "2M predictions/day sustained in production"
  - "Retraining time: 8 h → 1.5 h with parallel pipeline"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

El modelo de scoring vigente tenía seis años, estaba entrenado en datos pre-pandemia
y mostraba una degradación silenciosa: AUC reportado en producción 7 puntos
por debajo del AUC de entrenamiento. El área de riesgo necesitaba un modelo
fresco con monitorización real, no un notebook que alguien corría una vez al
trimestre. El proyecto era end-to-end: desde el ETL de features hasta el
endpoint en producción con drift detection y reentrenamiento programado.
Trabajé codo a codo con el data scientist que diseñaba el modelo y el equipo
de plataforma que proveía la infraestructura base.

## Decisiones técnicas

El modelo final es un ensemble XGBoost + LightGBM con stacking logístico, pero
el verdadero trabajo estuvo en el feature store: consolidamos 120+ features
en Feast, con materialización online (DynamoDB) para la inferencia en
tiempo real y offline (Redshift) para el entrenamiento. Esto resolvió el
problema clásico de training-serving skew: el modelo veía exactamente las
mismas features en ambos lados, con lineage hasta la query SQL que las
origina. El serving corre en un SageMaker multi-model endpoint que hospeda
simultáneamente el modelo en producción y los challengers, permitiendo
canary releases sin duplicar infraestructura.

El pipeline de reentrenamiento se orquesta con Airflow: trigger mensual +
trigger por alertas de drift (Evidently AI monitorea PSI de las top-20
features y AUC estimado en una muestra etiquetada por el backoffice de
riesgo). MLflow registra cada experimento (params, métricas, artifacts) y
el Model Registry aplica una gate automática: solo se promueve a producción
un candidato que supere el AUC actual por al menos 1 punto en el holdout y
que no degrade ninguna métrica de fairness. Los features nuevos que entran
al store pasan por un data quality check (Great Expectations) que bloquea
la promoción si aparecen nulos inesperados o drifts de distribución.

## Lecciones aprendidas

La lección más subestimada: el modelo es la parte fácil. El 70% del esfuerzo
se fue en el feature store, el monitoring y los pipelines de datos. La
segunda lección es que el drift no es opcional: durante los primeros tres
meses en producción capturamos dos drifts significativos (uno por un cambio
regulatorio en la variable "antigüedad laboral", otro por un bug en el ETL
que empezó a truncar fechas), y sin monitorización habrían pasado meses
hasta que el AUC degradado se notara en los reportes trimestrales. Por
último, el modelo de fairness importó tanto como el de performance: trabajamos
con el equipo de riesgo para definir métricas de disparate impact por
segmento (edad, género, región) y las exponemos en el mismo dashboard que el
AUC, porque un modelo sesgado que "funciona técnicamente" no es un modelo
aceptable en banca.
