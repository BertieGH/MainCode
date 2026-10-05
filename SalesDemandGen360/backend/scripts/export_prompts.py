"""Write every model instruction to a Word document.

The same document the Prompts screen's Download button serves — both call
`services.prompt_export`, because a document generated two ways drifts into two
documents. This exists for the times a shell is closer to hand than a browser,
and for putting the file somewhere specific.

    cd backend
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/export_prompts.py
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/export_prompts.py -o ~/review.docx
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services import prompt_export


async def _run(out: Path) -> tuple[int, int]:
    engine = create_async_engine(str(get_settings().database_url))
    async with async_sessionmaker(engine)() as session:
        stages = await prompt_export.collect(session)
        data = prompt_export.build(stages)
    await engine.dispose()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return len(stages), sum(1 for s in stages if s.edited)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / prompt_export.FILENAME,
        help="where to write the document",
    )
    args = parser.parse_args()

    total, edited = asyncio.run(_run(args.out))
    print(f"{total} stages ({edited} edited) -> {args.out}")


if __name__ == "__main__":
    main()
