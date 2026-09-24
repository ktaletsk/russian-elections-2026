import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Выборы в Госдуму-2026: воспроизведение анализа «Медузы» по сырым данным

    Воспроизводим выкладки статьи [«Выборы в Госдуму-2026 — самые грязные парламентские выборы эпохи Путина»](https://meduza.io/feature/2026/09/24/vybory-v-gosdumu-2026-samye-gryaznye-parlamentskie-vybory-epohi-putina)
    («Медуза», 24.09.2026) **с нуля — по протоколам участковых избирательных комиссий (УИК)**, а не по картинкам из статьи.

    **Источники данных**

    | Выборы | Что это | Откуда |
    |---|---|---|
    | 2000–2021 | протоколы УИК всех федеральных выборов, собранные с izbirkom.ru Сергеем Шпилькиным | [github.com/dkobak/elections/data](https://github.com/dkobak/elections/tree/master/data) |
    | 2024 | протоколы УИК президентских выборов (сбор — Иван Шукшин) | там же |
    | 2026 | протоколы УИК (федеральный список), снимок публичных сводных таблиц ЦИК; значения протоколов не меняются | [neshodilina.netlify.app/api](https://neshodilina.netlify.app/api) (CDN `pub-9b41…r2.dev`) |

    **Методика** — та же, что использует «Медуза»: диаграммы «явка × результат» по УИКам и тест на
    «красивые» целые проценты [Кобака, Шпилькина и Пшеничникова](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/j.1740-9713.2018.01141.x)
    (*Significance*, 2018) с Монте-Карло-оценкой ожидаемого числа случайных пиков.
    Эталонная реализация — [`dkobak/elections`](https://github.com/dkobak/elections).

    > ⚠️ Данные 2026 года предварительные: ЦИК опубликовал не все протоколы
    > (нет Ленинградской области и оккупированных территорий). «Медуза» строила графики по 82 124 УИКам,
    > к моменту публикации их стало 88 113; здесь используется тот снимок, который скачан ниже.
    """)
    return


@app.cell
def imports():
    import io
    import json
    import time
    import zipfile
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests

    return Path, io, json, mo, np, pd, plt, requests


@app.cell
def config(Path):
    # Протоколы 2000–2024: репозиторий Д. Кобака, закреплён на конкретном коммите
    KOBAK_COMMIT = "bbcc7ab4766935bbcab063b8a74d9ac55ec929eb"
    KOBAK_RAW = f"https://raw.githubusercontent.com/dkobak/elections/{KOBAK_COMMIT}/data/"
    # Протоколы 2026: статический CDN проекта neshodilina (зеркало сводных таблиц ЦИК)
    NESHODILINA = "https://pub-9b41d66c14bb4c2fa747a03654838e30.r2.dev/data/"

    DATA_DIR = Path("data")
    DATA_DIR.mkdir(exist_ok=True)

    DUMA_YEARS = [2003, 2007, 2011, 2016, 2021, 2026]
    ALL_YEARS = [2000, 2003, 2004, 2007, 2008, 2011, 2012, 2016, 2018, 2021, 2024, 2026]
    PRESIDENTIAL = {2000, 2004, 2008, 2012, 2018, 2024}
    LEADER_NAME = {2000: "Путин", 2004: "Путин", 2008: "Медведев", 2012: "Путин",
                   2018: "Путин", 2024: "Путин"}  # в думских выборах лидер — «Единая Россия»
    return (
        ALL_YEARS,
        DATA_DIR,
        DUMA_YEARS,
        KOBAK_RAW,
        LEADER_NAME,
        NESHODILINA,
        PRESIDENTIAL,
    )


@app.cell
def load_historical(DATA_DIR, KOBAK_RAW, pd, requests):
    def _pick(table, include, exclude=()):
        """Колонки протокола, в названии которых есть любая из подстрок include."""
        return [c for c in table.columns
                if any(s in c for s in include) and not any(s in c for s in exclude)]


    def load_historical(year):
        """Протоколы УИК 2000–2024 → стандартная таблица (логика колонок как в dkobak/elections)."""
        path = DATA_DIR / f"{year}.csv.zip"
        if not path.exists():
            path.write_bytes(requests.get(KOBAK_RAW + f"{year}.csv.zip", timeout=120).content)
        table = pd.read_csv(path)

        leader = _pick(table, ["ПУТИН", "Путин", "Единая Россия", "ЕДИНАЯ РОССИЯ", "Медведев"])
        voters = _pick(table, ["Число избирателей, включенных", "Число избирателей, внесенных"])
        given = _pick(table, ["бюллетеней, выданных"])  # досрочно + в помещении + вне помещения
        received = _pick(table, ["действительных", "недействительных"], exclude=["отметок"])
        assert len(leader) == 1 and len(voters) == 1 and len(given) == 3 and len(received) == 2, year

        out = pd.DataFrame({
            "region": table["region"].values,
            "tik": table["tik"].values,
            "uik": table["uik"].values,
            "voters": table[voters[0]].values,
            "given": table[given].sum(axis=1).values,
            "received": table[received].sum(axis=1).values,
            "leader": table[leader[0]].values,
        })
        return out.dropna(subset=["leader"]).astype(
            {"voters": int, "given": int, "received": int, "leader": int}
        )

    return (load_historical,)


@app.cell
def load_2026(DATA_DIR, NESHODILINA, json, pd, requests):
    def load_2026(refresh=False):
        """Протоколы УИК 2026 (федеральный список) → стандартная таблица + метаданные снимка.

        Скачанный снимок сохраняется в data/, чтобы результаты были воспроизводимы:
        источник обновляется каждые ~15 минут, пока ЦИК догружает протоколы.
        """
        snap, meta_path = DATA_DIR / "2026_federal.parquet", DATA_DIR / "2026_meta.json"
        if refresh or not snap.exists():
            meta = requests.get(NESHODILINA + "meta.json", timeout=60).json()
            rows = []
            for r in meta["regions"]:
                if r["uiks"] == 0:
                    continue  # регион без опубликованных протоколов
                reg = requests.get(NESHODILINA + f"fed/r{r['id']}.json", timeout=120).json()
                for u in reg["uiks"]:
                    row = {"region": reg["region"], "tik": u["tik"], "uik": u["name"]}
                    row.update({f"line{i + 1}": v for i, v in enumerate(u["protocol"])})
                    row.update(dict(zip(reg["parties"], u["votes"])))
                    rows.append(row)
            pd.DataFrame(rows).to_parquet(snap)
            # ДЭГ публикуется не по участкам, а по округам — берём сводку по регионам
            regions_json = requests.get(NESHODILINA + "regions.json", timeout=60).json()
            meta_path.write_text(json.dumps(
                {"generated_at": meta["generated_at"], "stats": meta["stats"], "regions": regions_json},
                ensure_ascii=False))
        raw = pd.read_parquet(snap)
        meta = json.loads(meta_path.read_text())

        er = [c for c in raw.columns if "ЕДИНАЯ РОССИЯ" in c]
        assert len(er) == 1
        out = pd.DataFrame({
            "region": raw["region"].values,
            "tik": raw["tik"].values,
            "uik": raw["uik"].values,
            "voters": raw["line1"].values,  # число избирателей в списке
            "given": (raw["line3"] + raw["line4"] + raw["line5"]).values,  # выданные бюллетени
            "received": (raw["line9"] + raw["line10"]).values,  # недействительные + действительные
            "leader": raw[er[0]].values,
        })
        return out.dropna(subset=["leader"]).astype(
            {"voters": int, "given": int, "received": int, "leader": int}
        ), meta


    return (load_2026,)


@app.cell(hide_code=True)
def refresh_button(mo):
    refresh_2026 = mo.ui.run_button(label="⟳ Скачать свежий снимок 2026 года")
    refresh_2026
    return (refresh_2026,)


@app.cell
def elections(ALL_YEARS, load_2026, load_historical, pd, refresh_2026):
    def _is_deg(df, year):
        """Псевдо-УИКи дистанционного электронного голосования (в данных 2021 года)."""
        deg = df["tik"].astype(str).str.contains("Дистанционное электронное")
        if year == 2021:
            num = pd.to_numeric(df["uik"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
            deg |= (df["region"] == "город Москва") & num.between(5001, 5015)
        return deg


    def _prepare(df, year):
        df = df.assign(year=year, deg=_is_deg(df, year))
        df = df[~df["deg"] & (df["voters"] > 0)].copy()
        df["turnout"] = 100 * df["given"] / df["voters"]
        df["result"] = 100 * df["leader"] / df["received"].where(df["received"] > 0)
        return df


    table_2026, meta_2026 = load_2026(refresh=refresh_2026.value)
    elections = {y: _prepare(load_historical(y), y) for y in ALL_YEARS if y < 2026}
    elections[2026] = _prepare(table_2026, 2026)
    return elections, meta_2026


@app.cell(hide_code=True)
def data_md(elections, meta_2026, mo):
    mo.md(
        f"""
    ## Данные

    Снимок 2026 года: **{meta_2026["generated_at"]}**, УИКов с протоколом федерального списка — **{len(elections[2026]):,}**
    из {meta_2026["stats"]["total_uiks"]:,}. Для сравнимости везде используются только «бумажные» участки:
    псевдо-УИКи дистанционного электронного голосования (ДЭГ) из данных 2021 года исключены,
    а в 2026 году ЦИК публикует ДЭГ только по округам, не по участкам.
    """.replace(",", " ")
    )
    return


@app.cell
def summary(LEADER_NAME, PRESIDENTIAL, elections, pd):
    def _row(y, d):
        return {
            "Год": y,
            "Выборы": "президент" if y in PRESIDENTIAL else "Госдума",
            "Лидер": LEADER_NAME.get(y, "Единая Россия"),
            "УИКов": len(d),
            "Избирателей": int(d["voters"].sum()),
            "Явка, %": round(100 * d["given"].sum() / d["voters"].sum(), 2),
            "Результат лидера, %": round(100 * d["leader"].sum() / d["received"].sum(), 2),
        }


    summary_table = pd.DataFrame([_row(y, d) for y, d in elections.items()])
    summary_table
    return (summary_table,)


@app.cell
def plot_helpers(np, plt):
    BG = "#F0EEE6"  # фон графиков «Медузы»
    C_OLD, C_NEW = "#555555", "#B8995E"
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    })


    def jittered(df, seed=42, for_histogram=False):
        """Явка и результат по УИКам с шумом U(-0.5, 0.5) в числителе, как у Кобака:
        убирает артефакты деления на маленьких участках, не размывая целые проценты.

        Для диаграмм рассеяния оставляем УИКи со 100% явкой и прижимаем точки к [0, 100];
        для гистограмм берём критерий Кобака (выдано < избирателей) и не обрезаем значения.
        """
        rng = np.random.default_rng(seed)
        full = df["given"] < df["voters"] if for_histogram else df["given"] <= df["voters"]
        d = df[(df["received"] > 0) & full]
        x = 100 * (d["given"] + rng.random(len(d)) - 0.5) / d["voters"]
        y = 100 * (d["leader"] + rng.random(len(d)) - 0.5) / d["received"]
        if not for_histogram:
            x, y = x.clip(0, 100), y.clip(0, 100)
        return d.assign(x=x, y=y)


    def comet_axes(ax, title=None, ylabel="Результат «Единой России», %"):
        ax.set_xlim(0, 101)
        ax.set_ylim(0, 101)
        ax.set_aspect("equal")
        ax.set_xticks(range(0, 101, 20))
        ax.set_yticks(range(0, 101, 20))
        ax.set_xlabel("Явка, %")
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title, loc="left", fontweight="bold")

    return C_NEW, C_OLD, comet_axes, jittered


@app.cell(hide_code=True)
def fig1_md(mo):
    mo.md(r"""
    ## 1. Общая картина: «хвост» стал «телом»

    Каждая точка — один УИК: по горизонтали явка, по вертикали результат «Единой России».
    В 2021 году основная масса участков — плотное «ядро» около 35–40% явки и ~30% за ЕР, плюс «хвост кометы»
    вправо-вверх и сетка сгущений на круглых значениях. В 2026-м хвост превратился в многокластерное «тело»,
    а ядро истончилось.
    """)
    return


@app.cell
def fig_comets(comet_axes, elections, jittered, plt):
    def _fig_comets():
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.6), layout="constrained")
        for ax, year in zip(axes, [2021, 2026]):
            d = jittered(elections[year])
            ax.scatter(d["x"], d["y"], s=0.25, c="k", alpha=0.35, linewidths=0, rasterized=True)
            comet_axes(ax, f"{year}: {len(d):,} УИКов".replace(",", " "))
        fig.suptitle("Распределение УИКов по явке и результату «Единой России»",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig


    _fig_comets()
    return


@app.cell
def comet_core(DUMA_YEARS, elections, np, pd, summary_table):
    from scipy.ndimage import gaussian_filter


    def comet_core(df, sigma=2.0, window=(5, 90)):
        """Явка и результат лидера в точке максимальной плотности УИКов.

        Поиск ограничен окном `window`, чтобы не зацепить сгусток участков с явкой и результатом ~100%.
        """
        d = df[df["received"] > 0]
        edges = np.arange(0, 101, 1.0)
        h, _, _ = np.histogram2d(d["turnout"].clip(0, 99.99), d["result"].clip(0, 99.99), bins=[edges, edges])
        centers = edges[:-1] + 0.5
        m = (centers >= window[0]) & (centers <= window[1])
        s = gaussian_filter(h, sigma)[np.ix_(m, m)]
        i, j = np.unravel_index(np.argmax(s), s.shape)
        return centers[m][i], centers[m][j]


    def _core_row(y):
        x, r = comet_core(elections[y])
        ys = [comet_core(elections[y], s)[1] for s in (1, 2, 3, 4)]
        official = summary_table.set_index("Год").loc[y, "Результат лидера, %"]
        return {"Год": y, "Ядро: явка, %": x, "Ядро: ЕР, %": r,
                "Ядро: ЕР при σ=1…4": f"{min(ys)}–{max(ys)}",
                "Официально (бумага), %": official,
                "Официально − ядро, п.п.": round(official - r, 1)}


    core_table = pd.DataFrame([_core_row(y) for y in DUMA_YEARS])
    core_table
    return (core_table,)


@app.cell(hide_code=True)
def core_md(core_table, mo):
    _c = core_table.set_index("Год")
    mo.md(
        f"""
    ### Где находится «ядро» кометы

    Положение ядра — максимум сглаженной плотности УИКов на плоскости «явка × результат»
    (сетка 1 п.п., гауссово сглаживание σ = 2 п.п.; сгусток у 100%/100% исключён из поиска).
    Для 2003–2021 годов эти оценки совпадают с грубыми оценками ядра в
    [`dkobak/elections`](https://github.com/dkobak/elections/blob/master/analysis/2021/duma2021.ipynb).

    «Медуза» пишет, что ядро поднялось с ~30% до ~35%. По нашим данным — с
    **{_c.loc[2021, "Ядро: ЕР, %"]}%** до **{_c.loc[2026, "Ядро: ЕР, %"]}%**
    (при σ от 1 до 4 п.п.: {_c.loc[2021, "Ядро: ЕР при σ=1…4"]}% → {_c.loc[2026, "Ядро: ЕР при σ=1…4"]}%).
    Направление то же, но сдвиг скорее ~3 п.п., чем ~5. Разрыв между официальным результатом
    по «бумажным» УИКам и ядром при этом вырос с {_c.loc[2021, "Официально − ядро, п.п."]} до {_c.loc[2026, "Официально − ядро, п.п."]} п.п. —
    максимум за все думские выборы.
    """
    )
    return


@app.cell(hide_code=True)
def regions_md(mo):
    mo.md(r"""
    ## 2. Картина по регионам: «московский столб»

    Слева от основного кластера в 2026 году появился разреженный вертикальный «столб» — это бумажные участки Москвы.
    Сдвиг влево объясняется ДЭГ: большинство москвичей голосовали дистанционно, и на участки пришли немногие.
    Петербург в 2021-м был похож на Москву, а в 2026-м «уехал» в противоположную сторону. Чечня не изменилась.
    """)
    return


@app.cell
def fig_regions(comet_axes, elections, jittered, plt):
    REGION_GROUPS = {
        "Москва": (["город Москва"], "#D9725B"),
        "Санкт-Петербург": (["город Санкт-Петербург"], "#5B84D6"),
        "Крым и Севастополь": (["Республика Крым", "город Севастополь"], "#8E6BBF"),
        "Чеченская республика": (["Чеченская Республика"], "#5FB3A8"),
    }


    def _fig_regions():
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.9), layout="constrained")
        for ax, year in zip(axes, [2021, 2026]):
            d = jittered(elections[year])
            ax.scatter(d["x"], d["y"], s=0.4, c="#CFCFCF", linewidths=0, rasterized=True)
            for label, (names, color) in REGION_GROUPS.items():
                r = d[d["region"].isin(names)]
                ax.scatter(r["x"], r["y"], s=2, c=color, linewidths=0, label=label, rasterized=True)
            comet_axes(ax, str(year))
        axes[0].legend(loc="upper left", markerscale=5, frameon=False, fontsize=9)
        fig.suptitle("Распределение УИКов по разным регионам", x=0.01, ha="left",
                     fontsize=14, fontweight="bold")
        return fig


    _fig_regions()
    return (REGION_GROUPS,)


@app.cell
def region_tables(REGION_GROUPS, elections, meta_2026, mo, pd):
    def _region_stats(year, names):
        d = elections[year]
        d = d[d["region"].isin(names)]
        return {"УИКов": len(d),
                "Явка, %": round(100 * d["given"].sum() / d["voters"].sum(), 1),
                "ЕР, %": round(100 * d["leader"].sum() / d["received"].sum(), 1),
                "Разброс ЕР по УИКам (IQR), п.п.": round(d["result"].quantile(0.75) - d["result"].quantile(0.25), 1)}


    region_table = pd.DataFrame([
        {"Регион": label, "Год": year, **_region_stats(year, names)}
        for label, (names, _) in REGION_GROUPS.items() for year in (2021, 2026)
    ])

    # Доля ДЭГ среди всех выданных бюллетеней (ЦИК публикует ДЭГ только по одномандатным округам)
    _rows = []
    for _r in meta_2026["regions"]["regions"]:
        _deg = _r["deg"]["fp"][3]  # бюллетени, выданные в ДЭГ (строка 4 протокола)
        if _deg > 0:
            _paper = _r["proto"][2] + _r["proto"][3] + _r["proto"][4]
            _rows.append({"Регион": _r["name"], "ДЭГ": _deg, "Бумага": _paper,
                          "Доля ДЭГ, %": round(100 * _deg / (_deg + _paper), 1)})
    deg_table = pd.DataFrame(_rows).sort_values("Доля ДЭГ, %", ascending=False, ignore_index=True)
    moscow_deg_share = deg_table.set_index("Регион").loc["город Москва", "Доля ДЭГ, %"]

    mo.vstack([
        mo.md(f"**Москва: {moscow_deg_share}%** проголосовавших выбрали ДЭГ (у «Медузы» — «почти 78%»)."),
        mo.hstack([mo.ui.table(region_table, selection=None, label="Регионы 2021 vs 2026"),
                   mo.ui.table(deg_table, selection=None, label="Доля ДЭГ по регионам, 2026")],
                  widths="equal"),
    ])
    return moscow_deg_share, region_table


@app.cell(hide_code=True)
def history_md(mo):
    mo.md(r"""
    ## 3. Динамика по годам: хуже на думских выборах при Путине ещё не было

    Плотность голосов на плоскости «явка × результат ЕР» на шести думских выборах.
    Близкое к нормальному распределение 2003 года сначала превращается в «комету» с ядром и хвостом,
    а затем — в многокластерное облако, где «гауссово» ядро трудно выделить.
    """)
    return


@app.cell(hide_code=True)
def history_controls(mo):
    heat_weight = mo.ui.dropdown(
        {"голосам (избирателям)": "voters", "участкам (УИКам)": "stations"},
        value="голосам (избирателям)", label="Взвешивать по",
    )
    heat_bin = mo.ui.dropdown({"0.5 п.п.": 0.5, "1 п.п.": 1.0}, value="0.5 п.п.", label="Шаг сетки")
    mo.hstack([heat_weight, heat_bin], justify="start")
    return heat_bin, heat_weight


@app.cell
def fig_history(
    DUMA_YEARS,
    elections,
    heat_bin,
    heat_weight,
    jittered,
    np,
    plt,
):
    from matplotlib.colors import PowerNorm


    def _fig_history(weight, step):
        fig, axes = plt.subplots(2, 3, figsize=(11, 7.6), layout="constrained")
        edges = np.arange(0, 100 + step, step)
        for ax, year in zip(axes.flat, DUMA_YEARS):
            d = jittered(elections[year])
            w = d["voters"] if weight == "voters" else None
            h, _, _ = np.histogram2d(d["x"], d["y"], bins=[edges, edges], weights=w)
            ax.imshow(h.T, origin="lower", extent=(0, 100, 0, 100), cmap="inferno",
                      norm=PowerNorm(0.5, vmin=0, vmax=np.percentile(h[h > 0], 99.7)),
                      interpolation="nearest")
            ax.text(6, 88, str(year), color="w", fontsize=12)
            ax.set_xticks([0, 50, 100])
            ax.set_yticks([0, 50, 100])
            ax.tick_params(labelsize=8)
        fig.supxlabel("Явка, %")
        fig.supylabel("Результат «Единой России», %")
        fig.suptitle("Распределение голосов по явке и результату партии власти на думских выборах",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig


    _fig_history(heat_weight.value, heat_bin.value)
    return


@app.cell(hide_code=True)
def peaks_md(mo):
    mo.md(r"""
    ## 4. Пики на «красивых» значениях: их стало намного больше

    Гистограмма УИКов по явке и по результату ЕР с шагом 0.1 п.п. (к числителю добавлен шум U(−0.5, 0.5),
    чтобы убрать артефакты деления на малых участках — как у Кобака и соавторов). При честном подсчёте
    заметных пиков на целых процентах быть не должно; при «рисовании» протоколов они появляются.
    """)
    return


@app.cell(hide_code=True)
def peaks_controls(ALL_YEARS, mo):
    compare_year = mo.ui.dropdown(
        {str(y): y for y in ALL_YEARS if y != 2026}, value="2021", label="Сравнить 2026 год с"
    )
    compare_year
    return (compare_year,)


@app.cell
def peaks_helper(C_NEW, C_OLD, elections, jittered, np, plt):
    def fig_peaks(old, new=2026, step=0.1):
        edges = np.arange(-step / 2, 100 + step / 2, step)
        centers = edges[:-1] + step / 2
        fig, axes = plt.subplots(2, 1, figsize=(11, 7.2), layout="constrained")
        for ax, col, label in zip(axes, ["x", "y"], ["Явка", "Результат лидера"]):
            for year, color in [(old, C_OLD), (new, C_NEW)]:
                h, _ = np.histogram(jittered(elections[year], for_histogram=True)[col], bins=edges)
                ax.plot(centers, h, lw=0.9, color=color, label=str(year))
            ax.set_xlim(0, 100)
            ax.set_xticks(range(0, 101, 5))
            ax.grid(axis="x", color="#CCCCCC", lw=0.8)
            ax.set_title(label, loc="left", fontweight="bold")
            ax.set_xlabel(f"{label}, %")
            ax.set_ylabel("Количество УИКов")
            ax.legend(frameon=False, ncols=2, loc="upper right")
        fig.suptitle(f"Пики на целочисленных значениях явки и результата — в {old} году и сейчас",
                     x=0.01, ha="left", fontsize=14, fontweight="bold")
        return fig

    return (fig_peaks,)


@app.cell
def fig_peaks_compare(compare_year, fig_peaks):
    fig_peaks(compare_year.value)
    return


@app.cell
def fig_peaks_2003(fig_peaks, mo):
    mo.vstack([
        mo.md("Сравнение с 2003 годом — так выглядит подсчёт без массовой подмены протоколов:"),
        fig_peaks(2003),
    ])
    return


@app.cell(hide_code=True)
def mc_md(mo):
    mo.md(r"""
    ## 5. Сколько УИКов с аномально круглыми значениями

    Методика [Кобака, Шпилькина и Пшеничникова](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/j.1740-9713.2018.01141.x):
    считаем УИКи, у которых явка **или** результат лидера лежит в пределах ±0.05 п.п. от целого процента,
    и вычитаем ожидаемое число таких УИКов при честном подсчёте. Ожидание получаем Монте-Карло: для каждого
    участка голоса за лидера и выданные бюллетени 1000 раз разыгрываются из биномиального распределения с теми же
    параметрами. «Порог случайных пиков» — 99.9-й перцентиль случайного превышения.

    Для 2026 года считаем два варианта явки: по **выданным** бюллетеням (строки 3+4+5 протокола — так явка определена
    во всех остальных годах) и по бюллетеням, **найденным в ящиках** (строки 9+10). Второй вариант, судя по всему,
    использован в расчёте «Медузы»/Кобака: колонка `turnout` в CSV-выгрузке 2026 года содержит именно его.
    """)
    return


@app.cell
def mc_func(np):
    def integer_anomaly(df, nrep=1000, prctl=99.9, seed=42, binwidth=0.1, chunk=50):
        """Тест Кобака–Шпилькина–Пшеничникова на избыток «целых» процентов.

        Наблюдаемое число УИКов, у которых явка или результат лидера попадает в ±binwidth/2 от целого
        процента, сравнивается с Монте-Карло: для каждого УИКа голоса за лидера и выданные бюллетени
        заново разыгрываются из биномиального распределения с теми же n и p (1000 повторов).
        Критерии включения — как в AOAS-2016: ≥100 избирателей, явка и результат ≤ 99%.
        """
        d = df[(df["received"] > 0) & (df["voters"] >= 100)]
        d = d[(d["given"] / d["voters"] <= 0.99) & (d["leader"] / d["received"] <= 0.99)]
        V, G = d["voters"].to_numpy(), d["given"].to_numpy()
        R, L = d["received"].to_numpy(), d["leader"].to_numpy()

        def near_int(p):
            return np.abs(p - np.round(p)) <= binwidth / 2

        def counts(lead, giv):  # → [явка или результат, только результат, только явка]
            res, tur = near_int(100 * lead / R), near_int(100 * giv / V)
            return np.stack([(res | tur).sum(-1), res.sum(-1), tur.sum(-1)], axis=-1)

        observed = counts(L, G)
        rng = np.random.default_rng(seed)
        sims = np.concatenate([
            counts(rng.binomial(R, L / R, size=(chunk, len(d))), rng.binomial(V, G / V, size=(chunk, len(d))))
            for _ in range(nrep // chunk)
        ])
        expected = sims.mean(0)
        return {
            "n": len(d),
            "observed": observed,
            "expected": expected,
            "excess": observed - expected,
            "std": sims.std(0),
            "threshold": np.percentile(sims, prctl, axis=0) - expected,
        }


    return (integer_anomaly,)


@app.cell
def mc_run(
    ALL_YEARS,
    DATA_DIR,
    PRESIDENTIAL,
    elections,
    integer_anomaly,
    json,
    mo,
    pd,
):
    def _cached_anomaly(key, df, cache_path=DATA_DIR / "integer_mc_cache.json"):
        """Монте-Карло детерминирован (seed=42), поэтому результат кэшируется по отпечатку данных."""
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        fp = f"{key}|{len(df)}|{df['voters'].sum()}|{df['given'].sum()}|{df['received'].sum()}|{df['leader'].sum()}"
        if fp not in cache:
            a = integer_anomaly(df)
            cache[fp] = {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in a.items()}
            cache_path.write_text(json.dumps(cache))
        return cache[fp]


    _variants = [(y, str(y), elections[y]) for y in ALL_YEARS] + [
        (2026, "2026*", elections[2026].assign(given=elections[2026]["received"]))
    ]
    _rows = []
    for _y, _label, _df in mo.status.progress_bar(_variants, title="Монте-Карло по выборам"):
        _a = _cached_anomaly(_label, _df)
        _rows.append({
            "Год": _label, "Выборы": "президент" if _y in PRESIDENTIAL else "Госдума", "УИКов в тесте": _a["n"],
            "Избыток: явка или результат": round(_a["excess"][0], 1),
            "Избыток: только явка": round(_a["excess"][2], 1),
            "Избыток: только результат": round(_a["excess"][1], 1),
            "Порог случайных пиков": round(_a["threshold"][0], 1),
            "σ случайного разброса": round(_a["std"][0], 1),
        })
    integer_table = pd.DataFrame(_rows)
    integer_table
    return (integer_table,)


@app.cell
def fig_integer(C_NEW, PRESIDENTIAL, integer_table, np, plt):
    def _fig_integer():
        t = integer_table[integer_table["Год"] != "2026*"]
        alt26 = integer_table.set_index("Год").loc["2026*"]
        x = np.arange(len(t))
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        ax.plot(x, t["Избыток: явка или результат"], "-o", color="k", lw=2, mfc="w", mew=1.5,
                label="Явка или результат лидера")
        ax.plot(x, t["Избыток: только явка"], "-o", color="#5B84D6", lw=1.2, ms=4, label="Только явка")
        ax.plot(x, t["Избыток: только результат"], "-o", color="#D9725B", lw=1.2, ms=4, label="Только результат")
        ax.plot(x, t["Порог случайных пиков"], "--", color="#999999", lw=1.2, label="Порог случайных пиков (99.9%)")
        ax.plot(x[-1], alt26["Избыток: явка или результат"], "D", color=C_NEW, ms=7,
                label="2026, явка по бюллетеням в ящиках")
        for xi, v in zip(x, t["Избыток: явка или результат"]):
            ax.annotate(f"{v:.0f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
        ax.set_xticks(x, [f"{y}\n{'П' if int(y) in PRESIDENTIAL else 'Д'}" for y in t["Год"]])
        ax.set_ylabel("Избыток УИКов с «красивыми» значениями")
        ax.legend(frameon=False, loc="upper left")
        ax.set_title("Количество УИКов с «красивыми» значениями на парламентских (Д) и президентских (П) выборах",
                     loc="left", fontweight="bold")
        return fig


    _fig_integer()
    return


@app.cell
def reference_check(integer_table, io, mo, pd, requests):
    # Сверка с опубликованными цифрами (не используются в расчётах выше):
    # данные графика «Медузы» (Datawrapper) и Монте-Карло из репозитория Кобака для 2000–2021
    try:
        _meduza = pd.read_csv(io.StringIO(
            requests.get("https://datawrapper.dwcdn.net/raAug/1/dataset.csv", timeout=30).text))
    except requests.RequestException:
        _meduza = None
    mo.stop(_meduza is None, mo.md("_Сверка пропущена: не удалось скачать данные графика «Медузы» с Datawrapper._"))
    _meduza = _meduza.rename(columns={"Явка или результат лидера": "Медуза: избыток",
                                      "Порог случайных пиков": "Медуза: порог"})[["Год", "Медуза: избыток", "Медуза: порог"]]
    _ours = integer_table[integer_table["Год"] != "2026*"].assign(Год=lambda t: t["Год"].astype(int))
    reference_check = _ours[["Год", "УИКов в тесте", "Избыток: явка или результат", "Порог случайных пиков"]].merge(
        _meduza, on="Год", how="left")
    reference_check["Разница с «Медузой»"] = (reference_check["Избыток: явка или результат"] - reference_check["Медуза: избыток"]).round(1)
    mo.vstack([
        mo.md(f"""**Сверка.** Для 2000–2024 годов наш избыток совпадает с опубликованным с точностью до шума
    Монте-Карло. Для 2026 года «Медуза» даёт {_meduza.set_index("Год").loc[2026, "Медуза: избыток"]:.0f};
    у нас — {integer_table.set_index("Год").loc["2026*", "Избыток: явка или результат"]:.0f} при явке по бюллетеням
    в ящиках (как у них) и {integer_table.set_index("Год").loc["2026", "Избыток: явка или результат"]:.0f}
    при явке по выданным бюллетеням. Порог случайных пиков — 99.9-й перцентиль по 1000 симуляциям, т.е. практически
    максимум, поэтому он шумный от прогона к прогону."""),
        reference_check,
    ])
    return


@app.cell(hide_code=True)
def conclusions(
    core_table,
    elections,
    integer_table,
    mo,
    moscow_deg_share,
    pd,
    region_table,
):
    _c = core_table.set_index("Год")
    _i = integer_table.set_index("Год")
    _r = region_table.set_index(["Регион", "Год"])
    conclusions = pd.DataFrame([
        ("УИКов с протоколами (2026)", "82 124 (затем 88 113)", f"{len(elections[2026]):,}".replace(",", " ")),
        ("Ядро кометы, результат ЕР 2021 → 2026", "~30% → ~35%", f"{_c.loc[2021, 'Ядро: ЕР, %']}% → {_c.loc[2026, 'Ядро: ЕР, %']}%"),
        ("Москва: доля ДЭГ", "почти 78%", f"{moscow_deg_share}%"),
        ("Москва: явка на участках 2021 → 2026", "сдвиг влево («столб»)",
         f"{_r.loc[('Москва', 2021), 'Явка, %']}% → {_r.loc[('Москва', 2026), 'Явка, %']}%"),
        ("Петербург: явка / ЕР 2021 → 2026", "примерно вдвое выше",
         f"{_r.loc[('Санкт-Петербург', 2021), 'Явка, %']}/{_r.loc[('Санкт-Петербург', 2021), 'ЕР, %']}% → "
         f"{_r.loc[('Санкт-Петербург', 2026), 'Явка, %']}/{_r.loc[('Санкт-Петербург', 2026), 'ЕР, %']}%"),
        ("Чечня 2021 → 2026", "без изменений",
         f"{_r.loc[('Чеченская республика', 2021), 'Явка, %']}/{_r.loc[('Чеченская республика', 2021), 'ЕР, %']}% → "
         f"{_r.loc[('Чеченская республика', 2026), 'Явка, %']}/{_r.loc[('Чеченская республика', 2026), 'ЕР, %']}%"),
        ("Избыток «красивых» УИКов 2021", "~1 300", f"{_i.loc['2021', 'Избыток: явка или результат']:.0f}"),
        ("Избыток «красивых» УИКов 2026", "почти 2 250",
         f"{_i.loc['2026*', 'Избыток: явка или результат']:.0f} (явка по ящикам) / "
         f"{_i.loc['2026', 'Избыток: явка или результат']:.0f} (по выданным)"),
    ], columns=["Утверждение", "«Медуза»", "Наш расчёт"])

    mo.vstack([
        mo.md(r"""
    ## Итог: что воспроизвелось

    Все ключевые выводы статьи подтверждаются расчётом по сырым протоколам. Числа по прошлым выборам
    совпадают с опубликованными с точностью до шума Монте-Карло. Два расхождения:

    * **Ядро 2026 года** по нашей оценке ниже (~32–33%, а не ~35%), так что рост «истинного» результата ЕР
      с 2021 года — скорее ~3 п.п., чем ~5.
    * **Избыток «красивых» УИКов в 2026 году** зависит от определения явки. Если считать её по бюллетеням
      в ящиках (как, судя по всему, в расчёте «Медузы»), выходит ~2 235, как в статье. Если по выданным
      бюллетеням (как во всех прошлых годах), выходит ~2 430. Тогда 2026 год ещё сильнее отрывается
      от прежних думских выборов.
    """),
        conclusions,
    ])
    return


if __name__ == "__main__":
    app.run()
