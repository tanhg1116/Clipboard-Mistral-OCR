import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.services.state import Session, OcrEntry
from src.services.exporter import HTML_TEMPLATE


def test_html_template_present():
    assert "<!DOCTYPE html>" in HTML_TEMPLATE
