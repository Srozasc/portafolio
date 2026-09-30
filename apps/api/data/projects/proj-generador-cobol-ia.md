---
slug: proj-generador-cobol-ia
title_es: Generador Cobol Ia
title_en: Cobol Ia Generator
year: 2025
role_es: Full-Stack Engineer
role_en: Full-Stack Engineer
tags:
- python
- llm
- cobol
- code-generation
- ai-agents
stack_es:
- Python
stack_en:
- Python
summary_es: Proyecto sin descripcion (ver README del repositorio).
summary_en: Project without description (see README in the repository).
client: null
impact_es: null
impact_en: null
links:
  repo: https://github.com/Srozasc/generador-cobol-ia
  demo: null
  case_study: null
---

# 🚀 Generador COBOL IA

**Generador inteligente de código COBOL usando IA avanzada con LangChain y LangGraph**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-Latest-green.svg)](https://langchain.com)
[![Gemini](https://img.shields.io/badge/Gemini-3.0%20Pro-orange.svg)](https://deepmind.google/models/gemini/pro/)
[![Tests](https://img.shields.io/badge/Tests-72%20Passed-brightgreen.svg)](./tests/)
[![Coverage](https://img.shields.io/badge/Coverage-95%25-brightgreen.svg)](./tests/)
[![Version](https://img.shields.io/badge/Version-0.3.0-blue.svg)](https://github.com/Srozasc/generador-cobol-ia/releases)

## 📋 Descripción

El **Generador COBOL IA** es una herramienta avanzada que utiliza inteligencia artificial para generar código COBOL de alta calidad a partir de descripciones en lenguaje natural. Implementa un sistema de agentes especializados con capacidades de autocorrección y validación automática.

## ✨ Funcionalidades Principales

### 🤖 Agentes de IA Especializados
- **Agente Planificador**: Convierte lenguaje natural en planes técnicos estructurados
  - Detecta automáticamente modo de operación (creación/modificación)
  - Análisis de impacto para modificaciones
- **Agente Codificador**: Genera código COBOL de alta calidad siguiendo estándares empresariales
  - Generación de código nuevo desde cero
  - Modificación inteligente de programas existentes
- **Agente Documentador**: Genera documentación técnica completa *(Nuevo en v0.2.0)*
- **Sistema de Autocorrección**: Ciclo automático de validación y corrección de errores

### 🔧 Modo Modificación *(Nuevo en v0.3.0)*
- **Modificación de programas existentes**: Analiza y modifica código COBOL legacy
- **Análisis de impacto**: Identifica secciones afectadas por cambios
- **Preservación de estructura**: Mantiene la arquitectura original del programa
- **Validación de cambios**: Verifica que las modificaciones sean correctas

### 💾 Guardar Código Generado *(Nuevo en v0.3.0)*
- **Guardado automático**: Opción para guardar código al finalizar
- **Extracción de PROGRAM-ID**: Sugiere nombre de archivo basado en el programa
- **Formato .cbl**: Guarda con extensión estándar COBOL
- **Encoding UTF-8**: Compatibilidad con editores modernos

### 🏢 Cabeceras Empresariales Automáticas
- **Generación automática** de cabeceras COBOL estandarizadas
- **Inferencia inteligente** de sistema y subsistema basada en contexto
- **Información dinámica**: Fecha, autor, objetivos y mantenimiento
- **Formato empresarial**: Cumple con estándares corporativos de documentación

## 🏗️ Arquitectura

```
generador_cobol_ia/
├── agents/                 # Agentes de IA especializados
│   ├── planner.py         # Agente Planificador
│   ├── coder.py           # Agente Codificador + Cabeceras
│   └── documenter.py      # Agente Documentador
├── validators/            # Sistema de validación
│   ├── mock_validator.py  # Validador simulado (MVP)
│   └── mainframe_validator.py # Validador real (futuro)
├── core/                  # Orquestación central
│   └── graph.py          # Grafo LangGraph
├── tests/                 # Suite de pruebas completa
├── Documentacion/         # Documentación técnica
│   ├── inicial/          # Arquitectura y especificaciones
│   └── funcionalidades/  # Documentación de características
└── run_prototype.py      # CLI principal
```

## 🚀 Instalación y Configuración

### Prerrequisitos
- Python 3.11+
- Google AI Studio API Key (Gemini)
- (Opcional) OpenAI o Anthropic API Key
- Git

### Instalación
```bash
# Clonar repositorio
git clone https://github.com/Srozasc/generador-cobol-ia.git
cd generador-cobol-ia

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
copy .env.example .env
# Editar .env con tu API key
```

### Configuración de API Keys
```bash
# .env (ejemplo mínimo)
GOOGLE_API_KEY="tu_api_key_de_google_ai_studio"
LLM_MODEL="gemini-3-pro"         # Gemini 3 Pro (recomendado)
LLM_MAX_OUTPUT_TOKENS=64000      # 64K tokens para archivos grandes
LLM_TEMPERATURE=0.1

# Opcional
# OPENAI_API_KEY="sk-..."
# ANTHROPIC_API_KEY="sk-ant-..."
```

**Nota**: Gemini 3 Pro permite generar archivos COBOL completos de más de 1000 líneas gracias a su límite de 64K tokens de salida.

## 💻 Uso

### CLI Básico
```bash
# Ejecutar el generador
python run_prototype.py

# Opciones disponibles:
# 1. Generar nuevo programa COBOL
# 2. Documentar programa COBOL existente
# 3. Modificar programa existente (Nuevo en v0.3.0)
```

### Modo 1: Generar Nuevo Programa
```bash
# Ejemplo de solicitud
> "Crear programa SUPPGPR1 para gestionar información de proveedores"

# Al finalizar, se ofrece guardar el código:
¿Deseas guardar el código generado? (s/n): s
Nombre del archivo [SUPPGPR1.cbl]: 
✅ Código guardado exitosamente en: SUPPGPR1.cbl
```

### Modo 2: Documentar Programa Existente
```bash
# Seleccionar opción 2
Selecciona una opción (1-3): 2

# Proporcionar ruta del archivo COBOL
Ruta del archivo: ./ejemplo_codigo/SUPPGPR1.cbl

# El sistema analiza el código y genera documentación completa:
# - Descripción general del programa
# - Propósito y funcionalidad
# - Estructura de datos (FILE SECTION, WORKING-STORAGE)
# - Flujo de procedimientos
# - Secciones y párrafos principales
# - Análisis de complejidad

# Al finalizar, ofrece guardar la documentación:
¿Deseas guardar la documentación? (s/n): s
Nombre del archivo [SUPPGPR1_DOC.md]: 
✅ Documentación guardada exitosamente en: SUPPGPR1_DOC.md
```

**Ejemplo de Documentación Generada:**
```markdown
# Documentación Técnica: SUPPGPR1

## Descripción General
Programa para gestión de información de proveedores...

## Estructura de Datos
### FILE SECTION
- PROVEEDOR-FILE: Archivo maestro de proveedores

### WORKING-STORAGE SECTION
- WS-PROVEEDOR-RECORD: Registro de trabajo
  - WS-CODIGO-PROVEEDOR (X(10))
  - WS-NOMBRE-PROVEEDOR (X(50))
  ...

## Flujo de Procedimientos
1. MAIN-PROCESS: Proceso principal
2. LEER-PROVEEDOR: Lectura de registros
3. VALIDAR-DATOS: Validación de información
...
```

### Modo 3: Modificar Programa Existente *(Nuevo)*
```bash
# Seleccionar opción 3
Selecciona una opción (1-3): 3

# Proporcionar ruta del archivo
Ruta del archivo: ./ejemplo_codigo/SUPPGNF6.txt

# Describir la modificación
Tu solicitud: "Cambiar el umbral de la tabla de 30000 a 40000 entradas"

# El sistema analiza, modifica y valida el código
# Al finalizar, ofrece guardar el código modificado
```

### Ejemplo de Salida
```cobol
      ******************************************************************
      * PROGRAM-ID: SUPPGPR1                                           *
      * AUTHOR:     GENERADOR COBOL IA                                 *
      * DATE-WRITTEN: ENE-2025                                         *
      * SISTEMA:    SUMINISTROS                                        *
      * SUBSISTEMA: GESTION DE PROVEEDORES                             *
      * OBJETIVOS:  GESTIONAR INFORMACION DE PROVEEDORES               *
      * MANTENCIONES:                                                 *
      * DD/MM/YYYY AUTOR      DESCRIPCION                              *
      * 15/01/2025 COBOL-IA   CREACION INICIAL DEL PROGRAMA            *
      ******************************************************************

       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUPPGPR1.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROVEEDOR-RECORD.
           05  WS-CODIGO-PROVEEDOR    PIC X(10).
           05  WS-NOMBRE-PROVEEDOR    PIC X(50).
           05  WS-DIRECCION           PIC X(100).
           05  WS-TELEFONO            PIC X(15).
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY 'SISTEMA DE GESTION DE PROVEEDORES'.
           DISPLAY 'PROGRAMA: SUPPGPR1'.
           STOP RUN.
```

### Ejemplo de Flujo Completo con Datacom y Modularidad
```cobol
      ******************************************************************
      * PROGRAM-ID: SUPPGPR1                                           *
      * AUTHOR:     GENERADOR COBOL IA                                 *
      * DATE-WRITTEN: ENE-2025                                         *
      * SISTEMA:    SUMINISTROS                                        *
      * SUBSISTEMA: GESTION DE PROVEEDORES                             *
      * OBJETIVOS:  CONSULTAR Y ACTUALIZAR INFORMACION DE PROVEEDORES  *
      * MANTENCIONES:                                                 *
      * DD/MM/YYYY AUTOR      DESCRIPCION                              *
      * 15/01/2025 COBOL-IA   CREACION INICIAL DEL PROGRAMA            *
      ******************************************************************

       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUPPGPR1.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  RQST-AREA.
           05  RQST-RET-CODE       PIC 9(4) COMP.
       01  KEY-AREA.
           05  KEY-PROVEEDOR-ID    PIC 9(9).
       01  DATA-AREA.
           05  NOMBRE-PROVEEDOR    PIC X(30).

       PROCEDURE DIVISION.
       MAIN-PROCESS SECTION.
           MOVE 123456789 TO KEY-PROVEEDOR-ID.
           CALL 'DBNTRY' USING RQST-AREA KEY-AREA DATA-AREA.
           IF RQST-RET-CODE NOT = ZERO
               DISPLAY 'ERROR DATACOM: ' RQST-RET-CODE
               GO TO ERROR-HANDLING
           END-IF
           PERFORM ESTADISTICA
           STOP RUN.

       ERROR-HANDLING SECTION.
           DISPLAY 'ERROR EN PROCESO PRINCIPAL'.
           STOP RUN.

       ESTADISTICA SECTION.
           DISPLAY 'REGISTROS PROCESADOS: 1'.
```

## 🧪 Testing

### Ejecutar Tests
```bash
# Todos los tests
python -m pytest tests/ -v

# Tests específicos
python -m pytest tests/agents/ -v
python -m pytest tests/validators/ -v
python -m pytest tests/test_integration_flow.py -v

# Con cobertura
python -m pytest tests/ --cov=. --cov-report=html
```

### Suite de Tests
- **72 tests** implementados (21 nuevos en v0.3.0)
- **95%+ cobertura** de código
- **Tests unitarios** para cada componente
- **Tests de integración** end-to-end
- **Tests de modo modificación** (12 tests específicos)
- **Tests de funcionalidad de guardado** (4 tests)
- **Tests de cabeceras empresariales** (8 tests específicos)
- **Stubs de LLM**: `tests/conftest.py` implementa un stub determinista de Gemini
  - Detecta el modo del planificador usando el último mensaje humano
  - Genera código con cabecera empresarial y secciones modulares (`PERFORM`)
  - Incluye áreas Datacom (`RQST-AREA`, `KEY-AREA`, `DATA-AREA`) y manejo de errores en `DBNTRY`

## 📚 Documentación

### Documentación Técnica
- [Arquitectura del Sistema](./Documentacion/inicial/arquitectura.md)
- [Especificación de Características](./Documentacion/inicial/especificacion_de_caracteristicas.md)
- [Estrategia de Versionado](./Documentacion/inicial/estrategia_versionado.md)

### Funcionalidades
- [Cabeceras Empresariales](./Documentacion/funcionalidades/cabeceras_empresariales.md)
- [Ejemplos de Cabeceras](./Documentacion/funcionalidades/ejemplos_cabeceras.md)
- [Datacom DML y Áreas](./Documentacion/funcionalidades/datacom_dml.md)

## 🎯 Casos de Uso

### Sistemas Soportados
- **BANCARIO**: Cuentas, transacciones, créditos
- **SUMINISTROS**: Proveedores, compras, inventario
- **RECURSOS HUMANOS**: Empleados, nómina, personal
- **CONTABILIDAD**: Balances, asientos, finanzas
- **VENTAS**: Clientes, facturación, productos
- **INVENTARIO**: Stock, almacén, control

### Ejemplos de Solicitudes
```
✅ "Crear programa CTABANK1 para gestionar cuentas bancarias"
✅ "Desarrollar EMPGEST1 para administrar empleados"
✅ "Programa de inventario INVCTRL1 para control de stock"
✅ "Sistema contable para generar balance general"
```

## 🔧 Desarrollo

### Metodología TDD
1. **Escribir test** antes de implementar
2. **Implementar** funcionalidad mínima
3. **Refactorizar** y optimizar
4. **Validar** con tests de integración

### Convenciones de Código
- **PEP 8** para estilo Python
- **Type hints** obligatorios
- **Docstrings** en formato Google
- **Tests** para cada función pública

### Convenciones COBOL
- **Mayúsculas**: todo el código COBOL en MAYÚSCULAS.
- **Indentación**: 4 espacios en datos; 8 espacios en procedimientos.
- **Columnas**: 1–6 numeración (opcional), 7 indicador, 8–72 código.
- **Cabecera**: etiqueta `MANTENCIONES` en español, no `MAINTENANCE`.
- **Fechas**: `DATE-WRITTEN` en `MMM-YYYY`; entradas de `MANTENCIONES` en `DD/MM/YYYY`.
- **Secciones**: `MAIN-PROCESS SECTION.` y `ESTADISTICA SECTION.` con `PERFORM ESTADISTICA`.
- **Datacom**: verificar `RQST-RET-CODE` tras `CALL 'DBNTRY'`; desviar a `ERROR-HANDLING` si no es cero.

### Contribuir
```bash
# Fork del repositorio
git fork https://github.com/Srozasc/generador-cobol-ia.git

# Crear rama feature
git checkout -b feature/nueva-funcionalidad

# Implementar con TDD
# 1. Escribir tests
# 2. Implementar código
# 3. Validar tests

# Commit y push
git commit -m "feat(agents): nueva funcionalidad X"
git push origin feature/nueva-funcionalidad

# Crear Pull Request
```

## 📈 Roadmap

### ✅ Versión 0.1.0 (Completada)
- [x] MVP: Planner + Coder + Validator
- [x] Graph con LangGraph
- [x] CLI básico
- [x] Tests unitarios e integración

### ✅ Versión 0.2.0 (Completada)
- [x] Agente Documentador
- [x] Cabeceras empresariales automáticas
- [x] Inferencia de sistema/subsistema

### ✅ Versión 0.3.0 (Completada - Actual)
- [x] Modo modificación de programas existentes
- [x] Guardar código generado en archivos
- [x] Upgrade a Gemini 3 Pro (64K tokens)
- [x] Soporte para archivos grandes (>1000 líneas)

### 🔄 Versión 0.4.0 (Última Versión Prototipo - En Planificación)
- [ ] Validador real con mainframe (py3270)
- [ ] Análisis de código existente mejorado
- [ ] Detección automática de patrones COBOL
- [ ] Optimización de rendimiento
- [ ] Preparación para arquitectura API

### 🎯 Versión 1.0.0 (Producción - Q4 2025)
**Transformación a Producto de Producción**

- [ ] Refactorizar código para convertirlo en API
- [ ] Interfaz GUI completa
- [ ] Integración con herramientas de mainframe
- [ ] Otros puntos por definir según requerimientos del cliente

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. **Fork** el repositorio
2. **Crear** rama feature (`git checkout -b feature/AmazingFeature`)
3. **Commit** cambios (`git commit -m 'Add some AmazingFeature'`)
4. **Push** a la rama (`git push origin feature/AmazingFeature`)
5. **Abrir** Pull Request

### Guías de Contribución
- Seguir metodología **TDD**
- Mantener **cobertura >90%**
- Documentar **nuevas funcionalidades**
- Usar **convenciones de commit** establecidas

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Ver [LICENSE](LICENSE) para más detalles.

## 👥 Equipo

- **Desarrollador Principal**: [Srozasc](https://github.com/Srozasc)
- **Arquitecto IA**: Generador COBOL IA Team
- **QA**: Suite de Tests Automatizada

## 📞 Soporte

- **Issues**: [GitHub Issues](https://github.com/Srozasc/generador-cobol-ia/issues)
- **Documentación**: [Wiki del Proyecto](https://github.com/Srozasc/generador-cobol-ia/wiki)
- **Email**: [Contacto del Proyecto]

## 🏆 Reconocimientos

- **LangChain**: Framework de IA utilizado
- **OpenAI**: Modelos de lenguaje GPT
- **Comunidad COBOL**: Inspiración y estándares

---

**⭐ Si este proyecto te resulta útil, ¡dale una estrella en GitHub!**

**🚀 Versión**: 0.3.0 (Prototipo)  
**📅 Última Actualización**: Diciembre 2024  
**🔧 Estado**: Desarrollo Activo - Prototipo Funcional  
**🎯 Próxima Versión**: 0.4.0 (Validador Mainframe)
