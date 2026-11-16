"""M6 adapter for the page 33 A4 prescription."""
from .s2c_forms import from_m6, render as render_model


def render(p, status, fmt):
    return render_model(from_m6(p, status), fmt)
