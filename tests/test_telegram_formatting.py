from app.telegram_formatting import render_telegram_html


def test_bold_price_and_markdown_hard_break() -> None:
    source = "Шиномонтаж R18 — **3200 ₽** за комплект.\\\nБалансировка включена."
    assert render_telegram_html(source) == (
        "Шиномонтаж R18 — <b>3200 ₽</b> за комплект.\n"
        "Балансировка включена."
    )


def test_escapes_model_html_and_supports_common_markdown() -> None:
    source = "<script>x</script> *важно* ~~старое~~ `R18`"
    assert render_telegram_html(source) == (
        "&lt;script&gt;x&lt;/script&gt; <i>важно</i> "
        "<s>старое</s> <code>R18</code>"
    )


def test_fenced_code_and_safe_link() -> None:
    source = "```\n<a>&\n```\n[Сайт](https://example.com/a?q=1&x=2)"
    assert render_telegram_html(source) == (
        "<pre><code>&lt;a&gt;&amp;</code></pre>\n"
        '<a href="https://example.com/a?q=1&amp;x=2">Сайт</a>'
    )

