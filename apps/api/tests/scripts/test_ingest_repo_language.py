"""Tests for detect_language and rewrite_image_urls_to_absolute (Tarea 3)."""

from scripts.ingest_repo import (
    detect_language,
    rewrite_image_urls_to_absolute,
)


# ===========================================================================
# detect_language
# ===========================================================================

class TestDetectLanguage:
    """Heuristic detector based on stopword counts. 'en' is the fallback."""

    def test_empty_string_returns_en(self):
        assert detect_language("") == "en"

    def test_whitespace_only_returns_en(self):
        assert detect_language("   \n\t  ") == "en"

    def test_none_safe(self):
        # The current signature is `readme_text: str`. This is a defensive
        # check: empty-equivalent (None-like via empty) returns 'en'.
        assert detect_language("") == "en"

    def test_pure_spanish_returns_es(self):
        text = (
            "Este es un proyecto de prueba en español. La idea principal es "
            "implementar un sistema para detectar el idioma del README. "
            "Esperamos que funcione bien con texto que contiene palabras y "
            "expresiones comunes en español."
        )
        assert detect_language(text) == "es"

    def test_pure_english_returns_en(self):
        text = (
            "This is a test project written in English. The main goal is to "
            "implement a language detector for the README file. We expect it "
            "to work well with text that contains common English words and "
            "expressions used in software documentation."
        )
        assert detect_language(text) == "en"

    def test_spanish_with_accents(self):
        text = (
            "Configuración del sistema con detección automática. La "
            "instalación es muy sencilla: sólo hay que descargar el código "
            "fuente y luego ejecutar la prueba. Está disponible para "
            "cualquier usuario que quiera probarlo."
        )
        assert detect_language(text) == "es"

    def test_code_blocks_do_not_count(self):
        # README with prose in Spanish but lots of code block content in
        # English — the stopword counts should be based on prose only.
        text = """# Mi proyecto

Este proyecto hace cosas utiles. La instalación es muy sencilla.

```python
# This is a comment in English. The function does the following thing.
def the_function_for_the_thing():
    return "the result is the value we want"
```

La configuración del sistema es automática.
"""
        assert detect_language(text) == "es"

    def test_urls_do_not_count_as_words(self):
        text = (
            "Visita https://example.com/the-thing para más información. "
            "La documentación está en https://docs.example.com/the-docs y "
            "explica cómo funciona el sistema."
        )
        assert detect_language(text) == "es"

    def test_markdown_punctuation_stripped_before_counting(self):
        text = (
            "# Título con **negrita** y _cursiva_ y `código`\n\n"
            "Esta es una descripción del proyecto que incluye **palabras** y "
            "_formatos_ comunes en español."
        )
        assert detect_language(text) == "es"

    def test_inline_code_does_not_count(self):
        text = (
            "Usa el comando `git clone the-thing` para clonar el repositorio. "
            "Después ejecuta `make install the project`. La instalación es muy "
            "sencilla y rápida, no requiere configuración adicional."
        )
        assert detect_language(text) == "es"

    def test_html_tags_stripped(self):
        text = (
            "<p>This is the opening paragraph in English.</p>\n"
            "<div>La documentación está disponible en español. "
            "Es muy completa y útil para todos los usuarios.</div>\n"
            "<span>Esperamos que la disfrutes.</span>"
        )
        assert detect_language(text) == "es"

    def test_mixed_english_dominant_returns_en(self):
        text = (
            "The README is the main documentation file for this project. "
            "The setup is straightforward: clone the repository and run the "
            "tests. The configuration is automatic.\n\n"
            "Esta es una nota pequeña en español."
        )
        assert detect_language(text) == "en"

    def test_mixed_spanish_dominant_returns_es(self):
        text = (
            "La instalación es muy sencilla y rápida. La configuración es "
            "automática. La documentación está completa y es muy útil para "
            "todos los usuarios del proyecto.\n\n"
            "Note: the setup is straightforward."
        )
        assert detect_language(text) == "es"

    def test_tie_returns_en_fallback(self):
        # Equal counts of ES and EN stopwords → 'en'
        text = (
            "el un la una  the a an\n"
        )
        assert detect_language(text) == "en"

    def test_unknown_language_with_only_uncommon_words(self):
        # No stopwords from either list — fallback to 'en'
        text = "lorem ipsum dolor sit amet consectetur adipiscing elit"
        assert detect_language(text) == "en"

    def test_short_spanish_text(self):
        text = "La instalación es muy sencilla."
        assert detect_language(text) == "es"

    def test_short_english_text(self):
        text = "The installation is straightforward."
        assert detect_language(text) == "en"

    def test_realistic_spanish_readme_intro(self):
        text = """# Análisis de Datos en Tiempo Real

Este proyecto implementa un pipeline para procesar datos en tiempo real.
La idea principal es tomar datos de múltiples fuentes y aplicar técnicas
de análisis para generar métricas útiles.

## Instalación

La instalación es muy sencilla. Sólo hay que descargar el código fuente
y ejecutar el script de configuración. El sistema está pensado para
ser fácil de usar y mantener.

## Uso

El uso del sistema es muy directo. Los usuarios pueden configurar el
pipeline según sus necesidades y obtener resultados rápidamente.
"""
        assert detect_language(text) == "es"

    def test_realistic_english_readme_intro(self):
        text = """# Real-Time Data Pipeline

This project implements a pipeline for processing data in real time.
The main idea is to take data from multiple sources and apply analysis
techniques to generate useful metrics.

## Installation

The installation is straightforward. You only need to download the
source code and run the configuration script. The system is designed
to be easy to use and maintain.

## Usage

Using the system is very direct. Users can configure the pipeline
according to their needs and get results quickly.
"""
        assert detect_language(text) == "en"

    def test_returns_only_es_or_en(self):
        text = "anything goes here for the test 12345 !@#$%"
        result = detect_language(text)
        assert result in ("es", "en")


# ===========================================================================
# rewrite_image_urls_to_absolute
# ===========================================================================

class TestRewriteImageUrlsAbsolute:
    """Rewrite relative image paths to raw.githubusercontent.com URLs."""

    OWNER = "octocat"
    REPO = "Hello-World"
    BRANCH = "main"
    BASE = "https://raw.githubusercontent.com/octocat/Hello-World/main/"

    # ----- Markdown: simple relative paths ------------------------------

    def test_relative_dot_slash_rewritten(self):
        text = "![alt](./screenshot.png)"
        expected = f"![alt]({self.BASE}screenshot.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_bare_filename_rewritten(self):
        text = "![logo](logo.png)"
        expected = f"![logo]({self.BASE}logo.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_nested_relative_rewritten(self):
        text = "![docs](docs/screenshot.png)"
        expected = f"![docs]({self.BASE}docs/screenshot.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_deeply_nested_rewritten(self):
        text = "![a](assets/images/icons/logo.svg)"
        expected = f"![a]({self.BASE}assets/images/icons/logo.svg)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    # ----- Markdown: parent paths --------------------------------------

    def test_parent_relative_rewritten_clamping_at_root(self):
        # ../  resolves at the repo root → just the trailing segment.
        text = "![up](../screenshot.png)"
        expected = f"![up]({self.BASE}screenshot.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_parent_with_nested_rewritten(self):
        text = "![nested](../docs/screenshot.png)"
        expected = f"![nested]({self.BASE}docs/screenshot.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_multiple_parents_clamped(self):
        # ../../../foo clamps at root
        text = "![flat](../../../screenshot.png)"
        expected = f"![flat]({self.BASE}screenshot.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    # ----- Markdown: leave absolute URLs alone --------------------------

    def test_https_url_left_alone(self):
        text = "![alt](https://example.com/img.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_http_url_left_alone(self):
        text = "![alt](http://example.com/img.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_data_url_left_alone(self):
        text = "![inline](data:image/png;base64,iVBORw0KGgo=)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_mailto_left_alone(self):
        text = "![contact](mailto:dev@example.com)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_anchor_left_alone(self):
        # Anchors as image URLs are weird but technically valid syntax.
        text = "![section](#installation)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    # ----- Markdown: title attribute preserved --------------------------

    def test_markdown_image_with_title_preserved(self):
        text = '![alt](./screenshot.png "The screenshot")'
        expected = f'![alt]({self.BASE}screenshot.png "The screenshot")'
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    # ----- HTML <img src="..."> forms -----------------------------------

    def test_html_img_double_quotes(self):
        text = '<img src="./screenshot.png" alt="demo">'
        expected = f'<img src="{self.BASE}screenshot.png" alt="demo">'
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_html_img_single_quotes(self):
        text = "<img src='./logo.png' alt='logo' />"
        expected = f"<img src='{self.BASE}logo.png' alt='logo' />"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_html_img_absolute_url_left_alone(self):
        text = '<img src="https://cdn.example.com/img.png" alt="x">'
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    # ----- Multiple images in one README --------------------------------

    def test_multiple_images_rewritten(self):
        text = (
            "![a](./one.png)\n"
            "Some text.\n"
            "![b](./two.png)\n"
            "More text.\n"
            "![c](docs/three.png)\n"
        )
        expected = (
            f"![a]({self.BASE}one.png)\n"
            "Some text.\n"
            f"![b]({self.BASE}two.png)\n"
            "More text.\n"
            f"![c]({self.BASE}docs/three.png)\n"
        )
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_mixed_markdown_and_html(self):
        text = (
            "![md](./md.png)\n"
            '<img src="./html.png">\n'
        )
        expected = (
            f"![md]({self.BASE}md.png)\n"
            f'<img src="{self.BASE}html.png">\n'
        )
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_some_absolute_some_relative(self):
        text = (
            "![a](https://example.com/abs.png)\n"
            "![b](./rel.png)\n"
        )
        expected = (
            "![a](https://example.com/abs.png)\n"
            f"![b]({self.BASE}rel.png)\n"
        )
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    # ----- Non-image markdown links left alone -------------------------

    def test_non_image_link_left_alone(self):
        text = "[docs](./README.md)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_link_with_image_text_left_alone(self):
        # ![alt](url) is an image. [text](url) is a link. Only images rewritten.
        text = "Click [here](./docs.md) for the documentation."
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    # ----- Edge cases ---------------------------------------------------

    def test_empty_string_unchanged(self):
        assert rewrite_image_urls_to_absolute(
            "", self.OWNER, self.REPO, self.BRANCH
        ) == ""

    def test_no_images_unchanged(self):
        text = (
            "# Title\n"
            "\n"
            "Some prose with **bold** and *italic*.\n"
            "\n"
            "- bullet one\n"
            "- bullet two\n"
        )
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == text

    def test_alt_can_contain_special_chars(self):
        # The alt may contain brackets or spaces but should not break the parser.
        text = "![a [b] c](./img.png)"
        expected = f"![a [b] c]({self.BASE}img.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_branch_included_in_base_url(self):
        text = "![a](./x.png)"
        out = rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, "feature/my-branch"
        )
        assert "raw.githubusercontent.com" in out
        assert "/feature/my-branch/" in out

    def test_owner_and_repo_in_base_url(self):
        text = "![a](./x.png)"
        out = rewrite_image_urls_to_absolute(text, "foo", "bar", "main")
        assert "raw.githubusercontent.com/foo/bar/main/" in out

    def test_dot_segments_normalized(self):
        # `foo/./bar/x.png` should normalize to `foo/bar/x.png`
        text = "![a](foo/./bar/x.png)"
        expected = f"![a]({self.BASE}foo/bar/x.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected

    def test_trailing_dot_segment_dropped(self):
        # `foo/bar/.` should normalize to `foo/bar`
        text = "![a](foo/bar/./x.png)"
        expected = f"![a]({self.BASE}foo/bar/x.png)"
        assert rewrite_image_urls_to_absolute(
            text, self.OWNER, self.REPO, self.BRANCH
        ) == expected
