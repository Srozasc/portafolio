---
slug: proj-rag-customer
title_es: Chatbot RAG para atención al cliente
title_en: RAG chatbot for customer service
year: 2024
role_es: Senior Backend Engineer
role_en: Senior Backend Engineer
client: Fintech regional
tags:
  - python
  - openai
  - rag
  - vector-db
  - fastapi
  - llm
stack_es:
  - Python 3.11 + FastAPI
  - OpenAI (gpt-4o + text-embedding-3-small)
  - ChromaDB (collection persistente en disco)
  - LangChain (loaders, splitters, retrievers)
  - PostgreSQL (session state + feedback)
  - Redis (rate limiting + cache de respuestas)
  - Docker + GitHub Actions
stack_en:
  - Python 3.11 + FastAPI
  - OpenAI (gpt-4o + text-embedding-3-small)
  - ChromaDB (persistent on-disk collection)
  - LangChain (loaders, splitters, retrievers)
  - PostgreSQL (session state + feedback)
  - Redis (rate limiting + response cache)
  - Docker + GitHub Actions
summary_es: "Chatbot RAG para atención al cliente con base de conocimiento de 500+ documentos. Reduce 70% el tiempo de respuesta."
summary_en: "RAG chatbot for customer service with a 500+ document knowledge base. Reduces 70% response time."
impact_es:
  - "Tiempo medio de respuesta: 12 min → 3 min (-70%)"
  - "Resolución en primer contacto: 35% → 62%"
  - "Base de conocimiento: 500+ documentos indexados, reindex < 5 min"
  - "CSAT post-deployment: 4.3 / 5 (n=2.1K conversaciones)"
impact_en:
  - "Average response time: 12 min → 3 min (-70%)"
  - "First-contact resolution: 35% → 62%"
  - "Knowledge base: 500+ indexed documents, reindex < 5 min"
  - "Post-deployment CSAT: 4.3 / 5 (n=2.1K conversations)"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

La fintech atendía unas 800 conversaciones diarias por WhatsApp y email, y el
backlog crecía semana a semana. El equipo de soporte conocía las respuestas,
pero tardaba en consultar la base de conocimiento (manuales de producto,
políticas internas, normativa del regulador) y eso se traducía en tiempos de
respuesta largos y respuestas inconsistentes entre agentes. El objetivo era
construir un copiloto interno que sugiriera respuestas basadas en la KB y un
chatbot de cara al cliente para las preguntas frecuentes, ambos sobre la
misma fuente de verdad. Me tocó diseñar el sistema end-to-end y prototipar la
versión que después pasó a producción.

## Decisiones técnicas

Elegimos Retrieval-Augmented Generation clásico: los manuales y políticas se
cargan como Markdown en ChromaDB con embeddings de OpenAI
`text-embedding-3-small` (mejor relación calidad/costo que ada-002). El
retriever usa búsqueda híbrida (BM25 + dense) con un reranker liviano para
los top-20, y el LLM (gpt-4o) recibe los top-5 chunks como contexto con
instrucciones explícitas de "si no está en el contexto, decí que no sabés".
La API es FastAPI con streaming SSE para que el cliente vea la respuesta
mientras se genera.

Para evitar alucinaciones que inventen políticas regulatorias, el prompt fija
el idioma (es-AR), exige citas con slug de documento + número de sección, y
rechaza responder cuando la similitud del top chunk cae por debajo de un
umbral calibrado contra un set de 200 preguntas con respuesta conocida. La
ingesta es desacoplada: un job batch reprocesa la KB cuando cambia un manual,
y los embeddings se cachean por hash del chunk para no pagar dos veces por
el mismo párrafo.

## Lecciones aprendidas

La mayor sorpresa fue que el retrieval dominaba la calidad del producto: un
chunking naive por tokens rompía secciones regulatorias a mitad de párrafo y
producía respuestas técnicamente incorrectas aunque el LLM fuera bueno.
Pasamos a un splitter recursivo que respeta la jerarquía del Markdown
(`# > ## > ###`) con overlap de 200 tokens y eso solo nos dio +18% en
exactitud sobre el set de validación. La segunda lección es operacional: un
RAG sin un loop de feedback humano es un RAG que degrada en silencio.
Agregamos un endpoint de thumbs-up/down por respuesta y revisamos semanalmente
los negativos para detectar gaps de cobertura o documentos mal indexados. Por
último, optamos por ChromaDB en vez de un servicio gestionado (Pinecone,
Weaviate Cloud) porque el volumen no justificaba el costo fijo y el cliente
prefería mantener los embeddings on-prem por temas de compliance.
