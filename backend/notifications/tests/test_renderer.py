"""Unit tests for the template renderer."""

from django.test import SimpleTestCase

from notifications.renderer import extract_placeholders, render


class RenderTests(SimpleTestCase):
    def test_substitutes_simple_placeholders(self):
        out = render("Hi {{ first_name }}, you are {{ days }} days in.", {"first_name": "Amit", "days": 7})
        self.assertEqual(out, "Hi Amit, you are 7 days in.")

    def test_tolerates_whitespace_and_unknown_names(self):
        out = render("{{first_name}} / {{nope}} / {{  days  }}", {"first_name": "A", "days": 2})
        self.assertEqual(out, "A /  / 2")

    def test_filters(self):
        out = render("{{ name|upper }}-{{ name|lower }}-{{ when|date }}", {"name": "Ab", "when": "2026-09-26T11:43:00+00:00"})
        self.assertEqual(out, "AB-ab-2026-09-26")

    def test_none_renders_empty(self):
        self.assertEqual(render("x{{ v }}y", {"v": None}), "xy")

    def test_empty_template(self):
        self.assertEqual(render("", {}), "")

    def test_collapses_extra_blank_lines(self):
        out = render("a\n\n\n\nb", {})
        self.assertEqual(out, "a\n\nb")

    def test_resolves_nested_placeholder(self):
        out = render("{{ greeting }}", {"greeting": "Hello {{ first_name }}", "first_name": "Priya"})
        self.assertEqual(out, "Hello Priya")

    def test_extract_placeholders(self):
        found = extract_placeholders("{{a}}", "b {{ c }} {{a}}", "", None)
        self.assertEqual(found, ["a", "c"])
