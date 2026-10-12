"""Mark which suggested idea a published post came from.

    python link.py <idea_id> <post URL or shortcode>

The local dashboard does the same from a dropdown; this is for the GitHub
Actions setup (link.yml), where there is no dashboard to click.
"""

import sys

from src import db
from src.meta import _SHORTCODE

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    match = _SHORTCODE.search(sys.argv[2])
    shortcode = match.group(1) if match else sys.argv[2].strip("/ ")
    conn = db.connect("data/intelligence.db")
    db.init_schema(conn)
    try:
        db.link_idea(conn, int(sys.argv[1]), shortcode)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"idea #{sys.argv[1]} linked to {shortcode}")
