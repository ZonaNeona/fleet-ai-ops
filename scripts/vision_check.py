import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image, ImageDraw, ImageFont
from app.db import db, Space, FILES, System
from app.seed import create_space, add
from app.ai import run

im = Image.new("RGB", (900, 500), "white")
draw = ImageDraw.Draw(im)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
for i, line in enumerate(
    [
        "УЧЕБНЫЙ СЧЁТ № TEST-073",
        "Дата: 07.10.2026",
        "Поставщик: ООО Учебный сервис",
        "Диагностика автомобиля: 5000 рублей",
        "ИТОГО: 5000 рублей",
    ]
):
    draw.text((40, 40 + i * 75), line, font=font, fill="black")
with db() as s:
    sp = create_space(s, count=1)
    sid = sp.id
    f = add(
        s, sid, "file", "VISION-FIXTURE", {"name": "test-invoice.png", "ext": ".png", "creator_role": "owner"}
    )
    folder = FILES / sid
    folder.mkdir(parents=True, exist_ok=True)
    im.save(folder / (f.id + ".png"))
    fid = f.id
try:
    result = run(
        SimpleNamespace(
            space=sid,
            data={
                "mode": "document",
                "prompt": "Извлеки номер, дату, поставщика и итог из этого учебного счёта.",
                "file": fid,
                "role": "owner",
            },
        )
    )
    passed = "5000" in str(result.get("fields", {}).get("amount")) and "073" in str(
        result.get("fields", {}).get("number")
    )
    Path("reports/vision.json").write_text(
        json.dumps({"passed": passed, "result": result}, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {"passed": passed, "model": result["model"], "cost": result["cost"], "fields": result["fields"]},
            ensure_ascii=False,
        )
    )
finally:
    with db() as s:
        s.delete(s.get(Space, sid))
    import shutil

    shutil.rmtree(FILES / sid)
