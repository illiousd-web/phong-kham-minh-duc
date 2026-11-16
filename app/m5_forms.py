"""M5 adapter for the page 29/30/31 A4 laboratory forms."""
from .s2c_forms import laboratory, render as render_model


def render(p, group, fmt):
    return render_model(laboratory(p, group), fmt)
