"""Блок-схема и GIF-анимация: как данные Мосбиржи проходят через систему.
Запуск: python docs/make_animation.py   (нужен Pillow). Результат: docs/block_scheme.png и docs/how_it_works.gif
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1280, 800
FONTS = Path("C:/Windows/Fonts")


def font(size, bold=False):
    for name in (("calibrib.ttf" if bold else "calibri.ttf"), ("arialbd.ttf" if bold else "arial.ttf"),
                 "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
        for base in (FONTS, Path("/usr/share/fonts/truetype/dejavu")):
            if (base / name).exists():
                return ImageFont.truetype(str(base / name), size)
    return ImageFont.load_default()


BG, INK, MUTED, LINE = (244, 246, 249), (30, 41, 59), (91, 107, 127), (200, 209, 221)
NAVY, TEAL, GOLD, RED, GREEN, WHITE = (16, 36, 62), (31, 122, 122), (217, 154, 43), (200, 60, 50), (30, 138, 76), (255, 255, 255)
FT, FB, FS, FC = font(16), font(19, True), font(14), font(22, True)

# узлы: id -> (x, y, w, h, заголовок, подпись, цвет)
NODES = {
    "api": (40, 80, 230, 100, "API Мосбиржи", "ISS: история, справочники", NAVY),
    "af": (340, 80, 270, 100, "Airflow", "DAG advisory_pipeline, 19:00", NAVY),
    "minio": (680, 80, 240, 100, "MinIO", "сырьё как есть", NAVY),
    "loader": (660, 270, 240, 130, "Загрузчик", "контракт · часы торгов · допуск · дубли", TEAL),
    "pg": (40, 250, 280, 170, "PostgreSQL", "", NAVY),
    "ch": (980, 250, 260, 190, "ClickHouse", "", NAVY),
    "use": (980, 540, 260, 100, "Потребители", "аналитик · отчёт · SQL", NAVY),
    "tests": (40, 540, 280, 100, "Тесты БД: 15 из 15", "PostgreSQL · ClickHouse · MinIO", GREEN),
}
CHIPS = {  # id -> (узел, строка, текст)
    "pg_ref": ("pg", 0, "справочники: тикеры, сессии, допуски"),
    "pg_cli": ("pg", 1, "брокеры, заказчики, клиенты, журнал"),
    "pg_q": ("pg", 2, "карантин (только коды правил)"),
    "ch_ref": ("ch", 0, "ref_*: справочники"),
    "ch_fact": ("ch", 1, "market_trades, daily_bars"),
    "ch_agg": ("ch", 2, "свечи agg_ohlcv_1m, сигналы"),
}
EDGES = {  # id -> (точки, подпись, позиция подписи)
    "e1": ([(270, 130), (340, 130)], "запрос", (277, 100)),
    "e2": ([(610, 130), (680, 130)], "сырьё", (617, 100)),
    "e3": ([(780, 180), (780, 270)], "пакет", (792, 215)),
    "e4": ([(900, 335), (980, 335)], "принятые", (905, 310)),
    "e5": ([(180, 420), (180, 470), (1060, 470), (1060, 440)], "справочники по белому списку, без ID участников", (330, 476)),
    "e6": ([(660, 360), (320, 360)], "отклонённые: код правила", (400, 332)),
    "e8": ([(1110, 440), (1110, 540)], "", None),
}
EDGES["e8"] = ([(1160, 440), (1160, 540)], "SQL, отчёт", (1170, 482))

STEPS = [
    ("Будни, 19:00: после закрытия биржи Airflow запускает DAG advisory_pipeline.", {"af"}, [], set()),
    ("fetch: Airflow запрашивает у API Мосбиржи историю и карточки бумаг.", {"af", "api"}, [("e1", GOLD)], set()),
    ("Сырой ответ сохраняется в MinIO как есть; ID участников в сырьё не попадают.", {"af", "minio"}, [("e2", GOLD)], set()),
    ("load: справочники из PostgreSQL копируются в ClickHouse по белому списку полей.", {"pg", "ch"}, [("e5", GOLD)], {"pg_ref", "ch_ref"}),
    ("Загрузчик проверяет контракт, часы торгов 10:00–18:50, допуск тикера и дубли. Брак уходит в карантин.", {"minio", "loader"},
     [("e3", GOLD), ("e4", GREEN), ("e6", RED)], {"ch_fact", "pg_q"}),
    ("check: качество баров (high ≥ low, нет пропусков): 325 баров, ошибок 0.", {"ch"}, [], {"ch_fact"}),
    ("Сессия закрыта в 18:50: новые сделки не принимаются, считаются свечи и сигналы.", {"ch"}, [], {"ch_agg"}),
    ("Результат: аналитик читает ClickHouse и PostgreSQL, 15 тестов подтверждают работу БД.", {"ch", "use", "tests"}, [("e8", GOLD)], {"ch_agg", "pg_cli"}),
]


def box(d, x, y, w, h, fill, outline, width=2, r=14):
    d.rounded_rectangle((x, y, x + w, y + h), r, fill=fill, outline=outline, width=width)


def arrow(d, pts, color, width=3):
    d.line(pts, fill=color, width=width, joint="curve")
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    a = math.atan2(y1 - y0, x1 - x0)
    head = [(x1, y1), (x1 - 12 * math.cos(a - 0.4), y1 - 12 * math.sin(a - 0.4)), (x1 - 12 * math.cos(a + 0.4), y1 - 12 * math.sin(a + 0.4))]
    d.polygon(head, fill=color)


def point_at(pts, t):
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    pos = t * sum(seg)
    for i, s in enumerate(seg):
        if pos <= s or i == len(seg) - 1:
            k = 0 if s == 0 else min(1, pos / s)
            return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k)
        pos -= s


def center(d, text, f, cx, y, fill):
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def frame(step=None, t=1.0, final=False):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 20), "Как работает система: данные Мосбиржи → базы → результат", font=FC, fill=NAVY)
    active_nodes = STEPS[step][1] if step is not None else set()
    active_edges = dict(STEPS[step][2]) if step is not None else {}
    active_chips = STEPS[step][3] if step is not None else set()
    # рёбра
    for eid, (pts, label, lp) in EDGES.items():
        arrow(d, pts, active_edges.get(eid, LINE) if step is not None else MUTED, 4 if eid in active_edges else 3)
        if label:
            d.text(lp, label, font=FS, fill=MUTED)
    # узлы
    for nid, (x, y, w, h, title, sub, color) in NODES.items():
        on = nid in active_nodes
        if nid == "tests" and step is not None and step < 7:
            box(d, x, y, w, h, (236, 240, 245), LINE, 2)
            center(d, title, FB, x + w / 2, y + 22, (160, 172, 188))
            continue
        box(d, x, y, w, h, WHITE, GOLD if on else LINE, 5 if on else 2)
        d.rounded_rectangle((x, y, x + w, y + 38), 14, fill=color)
        d.rectangle((x, y + 20, x + w, y + 38), fill=color)
        d.text((x + 14, y + 8), title, font=FB, fill=WHITE)
        if sub:
            tw = d.textlength(sub, font=FT)
            lines = [sub] if tw < w - 24 else None
            if lines is None:
                words, lines, cur = sub.split(" "), [], ""
                for wd in words:
                    if d.textlength(cur + " " + wd, font=FT) > w - 24 and cur:
                        lines.append(cur); cur = wd
                    else:
                        cur = (cur + " " + wd).strip()
                lines.append(cur)
            for k, ln in enumerate(lines):
                d.text((x + 14, y + 48 + k * 22), ln, font=FT, fill=INK)
    # фишки внутри PG и CH
    for cid, (nid, row, text) in CHIPS.items():
        x, y, w, h, *_ = NODES[nid]
        cy = y + 50 + row * 38
        on = cid in active_chips
        col = RED if cid == "pg_q" and on else GOLD if on else LINE
        d.rounded_rectangle((x + 12, cy, x + w - 12, cy + 30), 8, fill=(255, 247, 228) if on else (246, 248, 251), outline=col, width=2)
        d.text((x + 20, cy + 6), text, font=FS, fill=INK)
    # часы торгов
    ty = 705
    d.text((40, ty - 30), "Торговый день:", font=FS, fill=MUTED)
    x0, x1 = 160, 1000
    hx = lambda hh: x0 + (hh - 10) / 9.2 * (x1 - x0)
    d.rounded_rectangle((hx(10), ty - 10, hx(18 + 50 / 60), ty + 10), 6, fill=(197, 230, 224))
    d.text((hx(10) + 8, ty - 9), "торги 10:00–18:50: сделки принимаются", font=FS, fill=INK)
    d.line((hx(18 + 50 / 60), ty - 18, hx(18 + 50 / 60), ty + 18), fill=NAVY, width=3)
    d.text((hx(18 + 50 / 60) - 98, ty - 38), "закрытие 18:50", font=FS, fill=NAVY)
    d.polygon([(hx(19), ty - 16), (hx(19) + 12, ty), (hx(19), ty + 16), (hx(19) - 12, ty)], fill=GOLD)
    d.text((hx(19) - 30, ty + 20), "19:00 DAG", font=FS, fill=GOLD)
    # подпись шага
    d.rectangle((0, H - 62, W, H), fill=NAVY)
    if step is not None:
        d.text((30, H - 52), f"Шаг {step + 1} из {len(STEPS)}", font=FB, fill=(255, 210, 122))
        d.text((190, H - 50), STEPS[step][0], font=FT if len(STEPS[step][0]) > 95 else FB, fill=WHITE)
        # бегущие точки
        for eid, col in active_edges.items():
            p = point_at(EDGES[eid][0], t)
            d.ellipse((p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9), fill=col, outline=WHITE, width=2)
    else:
        d.text((30, H - 50), "Блок-схема: API → Airflow → MinIO → загрузчик → PostgreSQL и ClickHouse → потребители; брак в карантин", font=FB, fill=WHITE)
    return img


def main():
    frame().save(OUT / "block_scheme.png")
    frames, durations = [], []
    for s in range(len(STEPS)):
        for k in range(10):
            frames.append(frame(s, min(1.0, k / 7))); durations.append(90)
        frames.append(frame(s, 1.0)); durations.append(900)
    frames.append(frame()); durations.append(1800)
    pal = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(OUT / "how_it_works.gif", save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print("готово:", OUT / "block_scheme.png", OUT / "how_it_works.gif", len(frames), "кадров")


if __name__ == "__main__":
    sys.exit(main())
