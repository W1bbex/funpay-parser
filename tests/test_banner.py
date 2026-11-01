from io import StringIO
import re

from rich.console import Console

import main


def test_banner_renders_aligned_logo_with_blue_pay(monkeypatch, capsys):
    output = StringIO()
    monkeypatch.setattr(
        main, "console", Console(file=output, width=80, force_terminal=True, color_system="truecolor", legacy_windows=False, no_color=False)
    )

    main.show_banner()

    rendered = output.getvalue()
    assert "\x1b[1;38;2;35;117;183m██████╗" in rendered
    assert "ANALYTICS & FULL MARKET SCRAPER PIPELINE" in rendered
    assert len(rendered.splitlines()) == 15  # 12 logo rows, subtitle, and two borders
    plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered).splitlines()
    icon_column = plain[1].index("█") - 6
    pixels = set()
    for row, line in enumerate(plain[1:13]):
        for column, char in enumerate(line[icon_column:icon_column + 13]):
            if char in "█▀":
                pixels.add((column, row * 2))
            if char in "█▄":
                pixels.add((column, row * 2 + 1))

    # The logo must contain two disconnected arrows, not a solid diamond.
    components = []
    while pixels:
        pending = [pixels.pop()]
        component = set(pending)
        while pending:
            x, y = pending.pop()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in pixels:
                    pixels.remove(point)
                    component.add(point)
                    pending.append(point)
        components.append(component)
    assert len(components) == 2
    assert all(len(component) > 40 for component in components)
    capsys.readouterr()
